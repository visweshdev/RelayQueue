"""Measure CSV workloads separately from historical noop benchmarks."""

import argparse
import asyncio
import json
import subprocess
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean

from bench.chaos_kill import compose
from bench.common import (
    client,
    machine,
    percentile,
    save_result,
    submit_many,
    wait_idle,
    wait_terminal,
)


def resource_snapshot(containers):
    output = subprocess.check_output(
        ["docker", "stats", "--no-stream", "--format", "{{json .}}", *containers],
        text=True,
        timeout=15,
    )
    totals = defaultdict(lambda: {"cpu_percent": 0.0, "memory_mib": 0.0})
    for line in output.splitlines():
        row = json.loads(line)
        memory = row["MemUsage"].split(" / ", 1)[0]
        unit = next(unit for unit in ("GiB", "MiB", "KiB", "B") if memory.endswith(unit))
        scale = {"GiB": 1024, "MiB": 1, "KiB": 1 / 1024, "B": 1 / 1024**2}
        service = containers[row["Name"]]
        totals[service]["cpu_percent"] += float(row["CPUPerc"].rstrip("%"))
        totals[service]["memory_mib"] += float(memory.removesuffix(unit)) * scale[unit]
    return totals


async def sample_resources(containers, stop):
    samples = []
    while not stop.is_set():
        snapshot = await asyncio.to_thread(resource_snapshot, containers)
        if stop.is_set():
            break
        samples.append(snapshot)
        try:
            await asyncio.wait_for(stop.wait(), timeout=1)
        except TimeoutError:
            continue
    services = set(containers.values())
    return {
        "sample_count": len(samples),
        "services": {
            service: {
                "mean_cpu_percent": round(mean(row[service]["cpu_percent"] for row in samples), 2),
                "max_sampled_memory_mib": round(
                    max(row[service]["memory_mib"] for row in samples), 2
                ),
            }
            for service in sorted(services)
        }
        if samples
        else {},
    }


def compose_containers(project, expected_workers):
    args = ("-p", project)
    containers = {}
    for line in compose(*args, "ps", "--status", "running", "--format", "json").splitlines():
        for container in json.loads(line) if line.startswith("[") else [json.loads(line)]:
            containers[container["Name"]] = container["Service"]
    workers = list(containers.values()).count("worker")
    if workers != expected_workers:
        raise RuntimeError(f"Expected {expected_workers} worker containers, found {workers}")
    return f"http://{compose(*args, 'port', 'api', '8000')}", containers


def durations(completed):
    timings = {"queue_ms": [], "execution_ms": [], "end_to_end_ms": []}
    for job in completed.values():
        if job["status"] != "succeeded" or job["attempt_seq"] != 1:
            continue
        created, started, finished = (
            datetime.fromisoformat(job[field])
            for field in ("created_at", "started_at", "finished_at")
        )
        timings["queue_ms"].append((started - created).total_seconds() * 1000)
        timings["execution_ms"].append((finished - started).total_seconds() * 1000)
        timings["end_to_end_ms"].append((finished - created).total_seconds() * 1000)
    return {
        "single_attempt_successes": len(timings["queue_ms"]),
        **{
            name: {f"p{p}": percentile(values, p) for p in (50, 95, 99)}
            for name, values in timings.items()
        },
    }


async def measure(jobs, rows, concurrency, project=None, expected_workers=None):
    content = "sku,quantity,unit_price\n" + "PRODUCT,2,12.50\n" * rows
    url, containers = (
        await asyncio.to_thread(compose_containers, project, expected_workers)
        if project
        else (None, {})
    )
    async with client(url) as api:
        await wait_idle(api)
        async with asyncio.timeout(65):
            while True:
                workers = await api.get("/v1/workers")
                workers.raise_for_status()
                active = sum(worker["alive"] for worker in workers.json())
                if expected_workers is None or active == expected_workers:
                    break
                await asyncio.sleep(1)
        stop = asyncio.Event()
        sampler = asyncio.create_task(sample_resources(containers, stop)) if containers else None
        try:
            started = time.perf_counter()
            identifiers, latencies, retries = await submit_many(
                api,
                jobs,
                task="sales_report",
                payload={"content": content},
                concurrency=concurrency,
            )
            submitted = time.perf_counter() - started
            completed = await wait_terminal(api, identifiers)
            elapsed = time.perf_counter() - started
        finally:
            stop.set()
            resources = await sampler if sampler else None
    valid = (
        all(
            job["status"] == "succeeded"
            and job["result"]["rows"] == rows
            and job["result"]["units"] == rows * 2
            and job["result"]["revenue"] == f"{rows * 25:.2f}"
            for job in completed.values()
        )
        and len(completed) == jobs
    )
    return {
        "task": "sales_report",
        "machine": machine(),
        "jobs": jobs,
        "rows_per_file": rows,
        "csv_bytes": len(content.encode()),
        "workers_observed": active,
        "concurrency": concurrency,
        "submission_seconds": submitted,
        "elapsed_seconds": elapsed,
        "jobs_per_minute": jobs / elapsed * 60,
        "submit_p95_ms": percentile(latencies, 95),
        "submit_p99_ms": percentile(latencies, 99),
        "submission_retries": retries,
        "job_latencies": durations(completed),
        "container_resources": resources,
        "outcomes": dict(Counter(job["status"] for job in completed.values())),
        "all_results_valid": valid,
        "note": "Includes HTTP submission and polling; single run, not sustained-rate latency.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=1000)
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--project", help="Sample resources from this running Compose project")
    parser.add_argument("--workers", type=int, help="Expected worker replicas")
    parser.add_argument("--output", type=Path, help="Write to a path instead of the default report")
    args = parser.parse_args()
    if args.jobs < 1 or not 1 <= args.rows <= 1000 or not 1 <= args.concurrency <= 64:
        parser.error("jobs must be positive, rows 1-1000, concurrency 1-64")
    if args.project and (args.workers is None or args.workers < 1):
        parser.error("--project requires a positive --workers value")
    if args.workers is not None and args.workers < 1:
        parser.error("--workers must be positive")
    result = asyncio.run(
        measure(args.jobs, args.rows, args.concurrency, args.project, args.workers)
    )
    if args.output:
        report = json.dumps(result, indent=2) + "\n"
        args.output.write_text(report, encoding="utf-8")
        print(report, end="")
    else:
        save_result(f"sales-{args.rows}-rows.json", result)
    if not result["all_results_valid"]:
        raise SystemExit("CSV results failed validation")


if __name__ == "__main__":
    main()
