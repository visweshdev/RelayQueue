"""Measure CSV workloads separately from historical noop benchmarks."""

import argparse
import asyncio
import time
from collections import Counter

from bench.common import client, machine, percentile, save_result, submit_many, wait_terminal


async def measure(jobs, rows, concurrency):
    content = "sku,quantity,unit_price\n" + "PRODUCT,2,12.50\n" * rows
    async with client() as api:
        workers = await api.get("/v1/workers")
        workers.raise_for_status()
        active = sum(worker["alive"] for worker in workers.json())
        started = time.perf_counter()
        identifiers, latencies, retries = await submit_many(
            api, jobs, task="sales_report", payload={"content": content}, concurrency=concurrency
        )
        submitted = time.perf_counter() - started
        completed = await wait_terminal(api, identifiers)
        elapsed = time.perf_counter() - started
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
        "outcomes": dict(Counter(job["status"] for job in completed.values())),
        "all_results_valid": valid,
        "note": "Includes HTTP submission and polling; single run, not sustained-rate latency.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=1000)
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=16)
    args = parser.parse_args()
    if args.jobs < 1 or not 1 <= args.rows <= 1000 or not 1 <= args.concurrency <= 64:
        parser.error("jobs must be positive, rows 1-1000, concurrency 1-64")
    result = asyncio.run(measure(args.jobs, args.rows, args.concurrency))
    save_result(f"sales-{args.rows}-rows.json", result)
    if not result["all_results_valid"]:
        raise SystemExit("CSV results failed validation")


if __name__ == "__main__":
    main()
