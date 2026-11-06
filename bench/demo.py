"""Record this terminal with asciinema, then convert the actual recording to GIF."""

import asyncio
import subprocess
from collections import Counter

from bench.chaos_kill import compose, kill_and_restart
from bench.common import client, submit_many, wait_terminal


async def main():
    async with client() as api:
        ids, _, _ = await submit_many(api, 20)
        print("Submitted 20 noop jobs")
        completed = await wait_terminal(api, ids)
        assert all(job["status"] == "succeeded" for job in completed.values())
        print("Verified: 20 succeeded")
        failed = await api.post(
            "/v1/jobs", json={"task": "flaky", "payload": {"fail_rate": 1}, "max_attempts": 2}
        )
        failed.raise_for_status()
        print("Flaky job will retry, then enter the dead-letter queue")
        sleeping, _, _ = await submit_many(api, 4, task="sleep", payload={"seconds": 5})
        workers = (await asyncio.to_thread(compose, "ps", "-q", "worker")).splitlines()
        if not workers:
            raise RuntimeError("No worker to demonstrate crash recovery")
        async with asyncio.timeout(30):
            while True:
                response = await api.get("/v1/jobs", params={"status": "running"})
                response.raise_for_status()
                running = [job for job in response.json()["items"] if job["id"] in sleeping]
                if running:
                    break
                await asyncio.sleep(0.05)
        owner = running[0]["locked_by"].split(":", 1)[0]
        victim = None
        for container in workers:
            inspected = await asyncio.to_thread(
                subprocess.run,
                ["docker", "inspect", "--format", "{{.Config.Hostname}}", container],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            if inspected.stdout.strip() == owner:
                victim = container
                break
        if victim is None:
            raise RuntimeError("Cannot identify the worker owning the demo job")
        await asyncio.to_thread(kill_and_restart, victim)
        print(f"SIGKILL + restart: worker {owner}, job {running[0]['id']}")
        print("Waiting for lease expiry, requeue and successful recovery...")
        results = await wait_terminal(api, ids + sleeping + [failed.json()["id"]], deadline_s=120)
        counts = dict(Counter(job["status"] for job in results.values()))
        assert counts == {"succeeded": 24, "dead": 1}
        print(f"Verified final outcomes: {counts}")
        detail = (await api.get(f"/v1/jobs/{running[0]['id']}")).json()
        outcomes = [attempt["outcome"] for attempt in detail["history"]]
        assert "lease_expired" in outcomes and outcomes[-1] == "succeeded"
        print(f"Recovered job history: {outcomes}")
        print(f"All {len(results)} accepted jobs accounted for")


if __name__ == "__main__":
    asyncio.run(main())
