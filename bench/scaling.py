import argparse
import asyncio
import json
import subprocess

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt

from bench.common import ROOT, client, machine, run_in_container, save_result, wait_idle
from bench.throughput import measure


async def main(jobs, container_client=False, resume=False):
    results = []
    current_machine = machine() if resume else None
    async with client() as api:
        await wait_idle(api)
    try:
        for workers in (1, 2, 4, 8):
            cached = ROOT / f"bench/results/scaling-{workers}.json"
            if resume and cached.exists():
                previous = json.loads(cached.read_text())
                if (
                    previous["jobs"] == jobs
                    and previous["workers"] == workers
                    and previous["outcomes"] == {"succeeded": jobs}
                    and not previous["missing_jobs"]
                    and not previous["drain_timed_out"]
                    and previous["machine"]["source_sha256"] == current_machine["source_sha256"]
                    and previous["machine"]["runtime_image_id"]
                    == current_machine["runtime_image_id"]
                    and bool(previous["machine"].get("load_generator")) == container_client
                ):
                    print(f"Reusing verified {workers}-worker result", flush=True)
                    results.append(previous)
                    continue
            await asyncio.to_thread(
                subprocess.run,
                ["docker", "compose", "up", "-d", "--scale", f"worker={workers}", "worker"],
                cwd=ROOT,
                check=True,
                timeout=120,
            )
            async with client() as api:
                async with asyncio.timeout(60):
                    while True:
                        response = await api.get("/v1/workers")
                        response.raise_for_status()
                        if sum(w["alive"] for w in response.json()) == workers:
                            break
                        await asyncio.sleep(1)
            if container_client:
                await asyncio.to_thread(
                    run_in_container,
                    "bench.throughput",
                    [
                        "--jobs",
                        str(jobs),
                        "--workers",
                        str(workers),
                        "--url",
                        "http://api:8000",
                        "--output",
                        f"scaling-{workers}.json",
                    ],
                )
                result = json.loads((ROOT / f"bench/results/scaling-{workers}.json").read_text())
            else:
                result = await measure(jobs, workers)
            save_result(f"scaling-{workers}.json", result)
            results.append(result)
    finally:
        await asyncio.to_thread(
            subprocess.run,
            ["docker", "compose", "up", "-d", "--scale", "worker=4", "worker"],
            cwd=ROOT,
            check=True,
            timeout=120,
        )
    save_result("scaling.json", results)
    plt.plot([r["workers"] for r in results], [r["jobs_per_minute"] for r in results], "o-")
    plt.xlabel("Workers")
    plt.ylabel("Measured jobs / minute")
    plt.title("RelayQueue noop scaling")
    plt.grid(alpha=0.2)
    plt.savefig(ROOT / "bench/results/scaling.png", dpi=160, bbox_inches="tight")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=20000)
    parser.add_argument("--container-client", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.jobs, args.container_client, args.resume))
