"""R4-R6 against the local Compose stack; actual results are written as JSON."""

import argparse
import asyncio
import time
from collections import Counter

from bench.chaos_kill import compose
from bench.common import client, machine, save_result, submit_many, wait_terminal


async def measure(scenario, jobs):
    async with client() as api:
        if scenario == "retry":
            ids, _, _ = await submit_many(api, jobs, task="flaky", payload={"fail_rate": 0.5})
        else:
            ids, _, _ = await submit_many(api, jobs, task="sleep", payload={"seconds": 0.2})
        started = time.monotonic()
        if scenario == "redis":
            await asyncio.to_thread(compose, "restart", "redis")
            # Force actual index loss even when the demo Redis uses AOF persistence.
            await asyncio.to_thread(compose, "exec", "-T", "redis", "redis-cli", "FLUSHDB")
        elif scenario == "graceful":
            try:
                await asyncio.to_thread(compose, "stop", "-t", "40", "worker")
                response = await api.get("/v1/jobs", params={"status": "running"})
                response.raise_for_status()
                if response.json()["items"]:
                    raise AssertionError("Running jobs remain after graceful worker shutdown")
            finally:
                await asyncio.to_thread(compose, "start", "worker")
        results = await wait_terminal(api, ids, deadline_s=300)
        outcomes = dict(Counter(job["status"] for job in results.values()))
        report = {
            "experiment": {"redis": "R4", "retry": "R5", "graceful": "R6"}[scenario],
            "machine": machine(),
            "submitted": jobs,
            "outcomes": outcomes,
            "missing_jobs": jobs - len(results),
            "elapsed_s": time.monotonic() - started,
        }
        save_result(f"reliability-{scenario}.json", report)
        assert outcomes.get("succeeded", 0) + outcomes.get("dead", 0) == jobs


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=["redis", "retry", "graceful"])
    parser.add_argument("--jobs", type=int, default=100)
    args = parser.parse_args()
    asyncio.run(measure(args.scenario, args.jobs))
