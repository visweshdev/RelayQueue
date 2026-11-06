"""P3/P5 Locust sweeps and P4 sequential idle pickup measurement."""

import argparse
import asyncio
import csv
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from bench.common import (
    ROOT,
    client,
    machine,
    percentile,
    run_in_container,
    save_result,
    submit_many,
    wait_terminal,
)


def load_test(rates, seconds, output="latency.json"):
    measurements = []
    for rate in rates:
        prefix = ROOT / "bench/results" / f"locust-{rate}"
        prefix.parent.mkdir(parents=True, exist_ok=True)
        run = subprocess.run(
            [
                sys.executable,
                "-m",
                "locust",
                "-f",
                "bench/locustfile.py",
                "--headless",
                "--host",
                os.getenv("BENCH_API_URL", "http://localhost:8000"),
                "-u",
                str(rate),
                "-r",
                str(rate),
                "-t",
                f"{seconds}s",
                "--csv",
                str(prefix),
                "--only-summary",
            ],
            cwd=ROOT,
            check=False,
            timeout=seconds + 60,
        )
        with Path(str(prefix) + "_stats.csv").open(newline="") as stream:
            aggregate = list(csv.DictReader(stream))[-1]
        measurements.append(
            {
                "target_rps": rate,
                "seconds": seconds,
                "actual_rps": float(aggregate["Requests/s"]),
                "p95_ms": float(aggregate["95%"]),
                "p99_ms": float(aggregate["99%"]),
                "failures": int(aggregate["Failure Count"]),
                "locust_exit_code": run.returncode,
            }
        )
    save_result(
        output,
        {
            "machine": machine(),
            "measurements": measurements,
            "first_p95_over_100ms_target_rps": next(
                (m["target_rps"] for m in measurements if m["p95_ms"] > 100), None
            ),
        },
    )


async def idle_pickup(count):
    samples = []
    async with client() as api:
        response = await api.get("/v1/queues/stats")
        response.raise_for_status()
        if any(
            row["count"] and row["status"] in {"queued", "running", "failed_retrying", "scheduled"}
            for row in response.json()
        ):
            raise RuntimeError("P4 requires idle queues")
        for _ in range(count):
            ids, _, _ = await submit_many(api, 1)
            job = (await wait_terminal(api, ids, deadline_s=60))[ids[0]]
            samples.append(
                (
                    datetime.fromisoformat(job["started_at"])
                    - datetime.fromisoformat(job["created_at"])
                ).total_seconds()
                * 1000
            )
    save_result(
        "pickup-idle.json",
        {
            "machine": machine(),
            "samples": count,
            "p95_ms": percentile(samples, 95),
            "raw_ms": samples,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rates", default="100")
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--idle-samples", type=int, default=0)
    parser.add_argument("--output", default="latency.json")
    parser.add_argument("--container-client", action="store_true")
    args = parser.parse_args()
    if args.container_client:
        run_in_container(
            "bench.latency",
            [
                "--rates",
                args.rates,
                "--seconds",
                str(args.seconds),
                "--output",
                args.output,
                "--idle-samples",
                str(args.idle_samples),
            ],
        )
    elif args.idle_samples:
        asyncio.run(idle_pickup(args.idle_samples))
    else:
        load_test([int(rate) for rate in args.rates.split(",")], args.seconds, args.output)
