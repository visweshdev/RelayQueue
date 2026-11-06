import argparse
import asyncio
import time
from collections import Counter
from datetime import datetime

from bench.common import (
    client,
    machine,
    percentile,
    save_result,
    snapshot,
    submit_many,
    wait_terminal,
)


async def measure(count=20000, workers=4, url="http://localhost:8000"):
    async with client(url) as api:
        started = time.perf_counter()
        identifiers, latencies, retries = await submit_many(api, count)
        submission_s = time.perf_counter() - started
        drain_timed_out = False
        try:
            jobs = await wait_terminal(api, identifiers)
        except TimeoutError:
            drain_timed_out = True
            jobs = await snapshot(api, identifiers)
        elapsed = time.perf_counter() - started
    pickup = [
        (
            datetime.fromisoformat(job["started_at"]) - datetime.fromisoformat(job["created_at"])
        ).total_seconds()
        * 1000
        for job in jobs.values()
        if job["started_at"]
    ]
    return {
        "experiment": "P1",
        "machine": machine(),
        "workers": workers,
        "jobs": count,
        "elapsed_s": elapsed,
        "submission_s": submission_s,
        "jobs_per_minute": sum(j["status"] == "succeeded" for j in jobs.values()) / elapsed * 60,
        "drain_timed_out": drain_timed_out,
        "submission_retries": retries,
        "submit_p95_ms": percentile(latencies, 95),
        "submit_p99_ms": percentile(latencies, 99),
        "pickup_under_load_p95_ms": percentile(pickup, 95),
        "outcomes": dict(Counter(job["status"] for job in jobs.values())),
        "missing_jobs": len(identifiers) - len(jobs),
        "configuration": {
            "task": "noop",
            "submit_concurrency": 32,
            "worker_count_source": "operator argument; verify compose scale",
        },
        "measurement_note": "Includes submission and polling overhead; load pickup is not idle P4.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=20000)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--output", default="throughput.json")
    args = parser.parse_args()
    if args.jobs < 1 or args.workers < 1:
        parser.error("jobs and workers must be positive")
    result = asyncio.run(measure(args.jobs, args.workers, args.url))
    save_result(args.output, result)
    if result["drain_timed_out"] or result["missing_jobs"]:
        raise SystemExit("Benchmark did not drain all accepted jobs; see saved results")


if __name__ == "__main__":
    main()
