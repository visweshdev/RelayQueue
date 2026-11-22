"""Verify a file checksum job's result after killing its worker in a disposable stack."""

import argparse
import asyncio
import json
import subprocess
import time
from hashlib import sha256
from pathlib import Path

import httpx

from bench.chaos_kill import compose, kill_and_restart
from bench.common import client, wait_idle

METRIC = "sum(fq_lease_expired_total) or vector(0)"


def checksum(content, iterations):
    for _ in range(iterations):
        content = sha256(content).digest()
    return content.hex()


async def read_counter(prometheus):
    response = await prometheus.get("/api/v1/query", params={"query": METRIC})
    response.raise_for_status()
    return float(response.json()["data"]["result"][0]["value"][1])


async def read_job(api, identifier):
    response = await api.get(f"/v1/jobs/{identifier}")
    response.raise_for_status()
    return response.json()


def inspect_project(project):
    args = ("-p", project)
    api_address = compose(*args, "port", "api", "8000")
    prometheus_address = compose(*args, "port", "prometheus", "9090")
    workers = compose(*args, "ps", "-q", "worker").splitlines()
    if len(workers) < 2:
        raise RuntimeError("Start the disposable project with at least two workers")
    owners = {}
    for container in workers:
        hostname = subprocess.check_output(
            ["docker", "inspect", "--format", "{{.Config.Hostname}}", container],
            text=True,
            timeout=10,
        ).strip()
        owners[hostname] = container
    return api_address, prometheus_address, owners


async def rehearse(project, path, iterations):
    content = path.read_bytes()
    if len(content) > 32768:
        raise ValueError("Use a UTF-8 input file of at most 32,768 bytes")
    api_address, prometheus_address, owners = await asyncio.to_thread(inspect_project, project)

    async with (
        client(f"http://{api_address}") as api,
        httpx.AsyncClient(base_url=f"http://{prometheus_address}", timeout=5) as prometheus,
    ):
        await wait_idle(api, deadline_s=30)
        before = await read_counter(prometheus)
        started = time.monotonic()
        response = await api.post(
            "/v1/jobs",
            json={
                "task": "cpu_hash",
                "payload": {"buffer": content.decode("utf-8"), "iterations": iterations},
                "timeout_s": 60,
                "max_attempts": 2,
            },
        )
        response.raise_for_status()
        identifier = response.json()["id"]
        print(f"Accepted checksum job {identifier}", flush=True)
        async with asyncio.timeout(20):
            while (running := await read_job(api, identifier))["status"] != "running":
                if running["status"] in {"succeeded", "dead", "cancelled"}:
                    raise RuntimeError("Job finished before fault injection; use more iterations")
                await asyncio.sleep(0.05)

        owner = running["locked_by"]
        await asyncio.to_thread(kill_and_restart, owners[owner.split(":", 1)[0]])
        print(f"Sent SIGKILL to worker {owner} and restarted its container", flush=True)

        async with asyncio.timeout(120):
            while True:
                job = await read_job(api, identifier)
                if job["status"] in {"succeeded", "dead", "cancelled"}:
                    break
                await asyncio.sleep(0.25)
        elapsed = time.monotonic() - started
        history = job["history"]
        if [attempt["outcome"] for attempt in history] != ["lease_expired", "succeeded"]:
            raise RuntimeError("Expected an expired attempt followed by a successful retry")
        if history[0]["worker_id"] != owner or not history[0]["requeued_at"]:
            raise RuntimeError("The killed owner's attempt was not recorded as requeued")
        expected = {
            "digest": await asyncio.to_thread(checksum, content, iterations),
            "iterations": iterations,
        }
        if job["status"] != "succeeded" or job["result"] != expected:
            raise RuntimeError("Retried checksum did not match the independently computed result")
        async with asyncio.timeout(45):
            while True:
                after = await read_counter(prometheus)
                if after > before:
                    break
                await asyncio.sleep(1)

    return {
        "job_id": identifier,
        "input_sha256": sha256(content).hexdigest(),
        "input_bytes": len(content),
        "status": job["status"],
        "result": job["result"],
        "history": history,
        "submit_to_observed_success_s": round(elapsed, 3),
        "prometheus_query": METRIC,
        "lease_expired_before": before,
        "lease_expired_after": after,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Compose project created for this drill")
    parser.add_argument("--input", type=Path, default=Path("examples/sales.csv"))
    parser.add_argument("--iterations", type=int, default=15_000_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 1_000_000_000:
        parser.error("--iterations must be between 1 and 1000000000")
    result = asyncio.run(rehearse(args.project, args.input, args.iterations))
    report = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    print(report, end="")


if __name__ == "__main__":
    main()
