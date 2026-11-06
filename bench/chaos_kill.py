"""R1-R3 against the current local Compose project. Only its workers are killed."""

import argparse
import asyncio
import random
import subprocess
import time
from collections import Counter
from datetime import datetime

from bench.common import (
    ROOT,
    attempt_details,
    client,
    machine,
    save_result,
    snapshot,
    submit_many,
    wait_idle,
    wait_terminal,
)


def compose(*args):
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout.strip()


def kill_and_restart(container):
    subprocess.run(
        ["docker", "kill", "--signal", "KILL", container],
        check=True,
        capture_output=True,
        timeout=15,
    )
    subprocess.run(["docker", "start", container], check=True, capture_output=True, timeout=30)


async def measure(jobs=10000, duration=120, interval=5, seed=42):
    containers = compose("ps", "-q", "worker").splitlines()
    if not containers:
        raise RuntimeError("No Compose workers running")
    rng = random.Random(seed)
    events, deadlines = [], {}
    async with client() as api:
        await wait_idle(api)

        async def killer():
            started = time.monotonic()
            next_kill = started + interval
            while time.monotonic() - started < duration:
                await asyncio.sleep(max(0, next_kill - time.monotonic()))
                next_kill += interval
                container = rng.choice(containers)
                hostname = (
                    await asyncio.to_thread(
                        subprocess.run,
                        ["docker", "inspect", "--format", "{{.Config.Hostname}}", container],
                        capture_output=True,
                        text=True,
                        check=True,
                        timeout=10,
                    )
                ).stdout.strip()
                await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "kill", "--signal", "KILL", container],
                    check=True,
                    capture_output=True,
                    timeout=15,
                )
                killed_at = time.monotonic() - started
                try:
                    # Identify the attempt left behind after death. A pre-kill
                    # snapshot races with short handlers finishing or starting.
                    active = await api.get("/v1/jobs", params={"status": "running", "limit": 100})
                    active.raise_for_status()
                    running = [
                        j
                        for j in active.json()["items"]
                        if (j["locked_by"] or "").startswith(hostname + ":")
                    ]
                    # Read the last lease deadline after its owner is dead: no heartbeat race.
                    script = (
                        "local t=redis.call('TIME'); local p=redis.call('PTTL',KEYS[1]); "
                        "if p<0 then return '-1' end; "
                        "return tostring(tonumber(t[1])+tonumber(t[2])/1000000+p/1000)"
                    )
                    for job in running:
                        expiry = float(
                            await asyncio.to_thread(
                                compose,
                                "exec",
                                "-T",
                                "redis",
                                "redis-cli",
                                "--raw",
                                "EVAL",
                                script,
                                "1",
                                f"fq:lease:{job['id']}",
                            )
                        )
                        if expiry > 0:
                            deadlines[f"{job['id']}:{job['attempt_seq']}"] = expiry
                finally:
                    await asyncio.to_thread(
                        subprocess.run,
                        ["docker", "start", container],
                        check=True,
                        capture_output=True,
                        timeout=30,
                    )
                events.append(
                    {
                        "container": container[:12],
                        "seconds": killed_at,
                        "observed_running_jobs": len(running),
                    }
                )

        chaos = asyncio.create_task(killer())
        try:
            identifiers, _, _ = await submit_many(
                api, jobs, task="sleep", payload={"seconds": 0.05}
            )
            await chaos
            terminal = await wait_terminal(api, identifiers, deadline_s=1200)
            details = await attempt_details(api, identifiers)
        finally:
            if not chaos.done():
                chaos.cancel()
            await asyncio.gather(chaos, return_exceptions=True)
            await asyncio.to_thread(compose, "start", "worker")
        discoverable = await snapshot(api, identifiers)
    duplicate_completions = sum(
        a["outcome"] == "lease_expired" and a["handler_finished_at"] is not None
        for job in details
        for a in job["history"]
    )
    recovery = []
    for job in details:
        for attempt in job["history"]:
            deadline = deadlines.get(f"{job['id']}:{attempt['attempt_no']}")
            if deadline and attempt["outcome"] == "lease_expired" and attempt["requeued_at"]:
                recovery.append(
                    datetime.fromisoformat(attempt["requeued_at"]).timestamp() - deadline
                )
    result = {
        "experiment": "R1-R3",
        "machine": machine(),
        "submitted": jobs,
        "seed": seed,
        "workers": len(containers),
        "kill_interval_s": interval,
        "duration_s": duration,
        "events": events,
        "missing_jobs": jobs - len(discoverable),
        "nonterminal_jobs": jobs - len(terminal),
        "outcomes": dict(Counter(job["status"] for job in terminal.values())),
        "observed_duplicate_completions": duplicate_completions,
        "observed_duplicate_rate": duplicate_completions / jobs,
        "lease_expiry_to_ready_s": recovery,
        "limitations": [
            "Duplicate completions are a lower bound: death before audit is invisible.",
            "Ready timing is the first durable observation after confirmed Redis republish.",
            "Redis and PostgreSQL wall clocks must be synchronized for cross-store timing.",
        ],
    }
    save_result("chaos.json", result)
    if result["missing_jobs"] or result["nonterminal_jobs"]:
        raise RuntimeError("Reliability accounting failed")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=10000)
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--interval", type=float, default=5)
    args = parser.parse_args()
    asyncio.run(measure(args.jobs, args.duration, args.interval))
