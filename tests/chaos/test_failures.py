import asyncio
import os
import random
import shutil
import subprocess
import time
from uuid import uuid4

import httpx
import pytest

from bench.common import ROOT, client, save_result, submit_many, wait_terminal

pytestmark = [pytest.mark.chaos, pytest.mark.slow]


@pytest.fixture(scope="module")
def stack():
    if os.getenv("RUN_CHAOS") != "1":
        pytest.skip("Set RUN_CHAOS=1 to run isolated real-process Docker chaos tests")
    if not shutil.which("docker"):
        pytest.fail("RUN_CHAOS requested but Docker is unavailable")
    project = f"fq-chaos-{uuid4().hex[:8]}"
    prefix = ["docker", "compose", "-p", project, "-f", "tests/chaos/compose.yaml"]

    def command(*args):
        return subprocess.run(
            [*prefix, *args], cwd=ROOT, check=True, capture_output=True, text=True, timeout=180
        ).stdout.strip()

    try:
        command("up", "-d", "--build")
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                if httpx.get("http://localhost:18800/ready", timeout=2).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            time.sleep(0.5)
        else:
            pytest.fail("Chaos stack did not become ready")
        yield command
    finally:
        command("down", "--volumes", "--remove-orphans")


async def running(api, identifier):
    async with asyncio.timeout(30):
        while True:
            response = await api.get(f"/v1/jobs/{identifier}")
            response.raise_for_status()
            job = response.json()
            if job["status"] == "running":
                return job
            await asyncio.sleep(0.05)


async def test_sigkill_mid_execution(stack):
    async with client("http://localhost:18800") as api:
        ids, _, _ = await submit_many(api, 1, task="sleep", payload={"seconds": 2})
        await running(api, ids[0])
        await asyncio.to_thread(stack, "kill", "-s", "SIGKILL", "worker")
        try:
            await asyncio.to_thread(stack, "start", "worker")
            result = await wait_terminal(api, ids, deadline_s=45)
            assert result[ids[0]]["status"] == "succeeded"
            detail = (await api.get(f"/v1/jobs/{ids[0]}")).json()
            assert any(a["outcome"] == "lease_expired" for a in detail["history"])
        finally:
            await asyncio.to_thread(stack, "start", "worker")


async def test_repeated_crashes_for_two_minutes(stack):
    rng = random.Random(42)
    async with client("http://localhost:18800") as api:
        ids, _, _ = await submit_many(api, 1200, task="sleep", payload={"seconds": 0.2})
        containers = (await asyncio.to_thread(stack, "ps", "-q", "worker")).splitlines()
        started = time.monotonic()
        try:
            while time.monotonic() - started < 120:
                victim = rng.choice(containers)
                await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "kill", "--signal", "KILL", victim],
                    check=True,
                    capture_output=True,
                    timeout=15,
                )
                await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "start", victim],
                    check=True,
                    capture_output=True,
                    timeout=30,
                )
                await asyncio.sleep(5)
            results = await wait_terminal(api, ids, deadline_s=180)
            assert len(results) == len(ids)
            assert all(job["status"] in {"succeeded", "dead"} for job in results.values())
        finally:
            await asyncio.to_thread(stack, "start", "worker")


async def test_redis_restart_loses_indexes_not_jobs(stack):
    async with client("http://localhost:18800") as api:
        ids, _, _ = await submit_many(api, 40, task="sleep", payload={"seconds": 0.1})
        started = time.monotonic()
        await asyncio.to_thread(stack, "restart", "redis")
        results = await wait_terminal(api, ids, deadline_s=60)
        assert len(results) == len(ids)
        save_result(
            "redis-restart-test.json",
            {
                "submitted": len(ids),
                "missing": len(ids) - len(results),
                "elapsed_s": time.monotonic() - started,
            },
        )


async def test_postgres_outage_readiness_and_recovery(stack):
    async with client("http://localhost:18800") as api:
        ids, _, _ = await submit_many(api, 30, task="sleep", payload={"seconds": 0.2})
        await asyncio.to_thread(stack, "stop", "postgres")
        try:
            assert (await api.get("/ready")).status_code == 503
            await asyncio.sleep(2)
        finally:
            await asyncio.to_thread(stack, "start", "postgres")
        assert len(await wait_terminal(api, ids, deadline_s=90)) == len(ids)


async def test_sigterm_drains(stack):
    async with client("http://localhost:18800") as api:
        ids, _, _ = await submit_many(api, 1, task="sleep", payload={"seconds": 1})
        await running(api, ids[0])
        try:
            await asyncio.to_thread(stack, "stop", "-t", "10", "worker")
            result = await wait_terminal(api, ids, deadline_s=10)
            assert result[ids[0]]["status"] == "succeeded"
        finally:
            await asyncio.to_thread(stack, "start", "worker")


async def test_lease_clock_is_redis_clock(stack):
    # The real worker container clock is never passed to claim/heartbeat Lua.
    script = "local t=redis.call('TIME'); return tostring(tonumber(t[1])*1000+tonumber(t[2])/1000)"
    before = float(
        await asyncio.to_thread(
            stack, "exec", "-T", "redis", "redis-cli", "--raw", "EVAL", script, "0"
        )
    )
    async with client("http://localhost:18800") as api:
        ids, _, _ = await submit_many(api, 1, task="sleep", payload={"seconds": 2})
        await running(api, ids[0])
        deadline = float(
            await asyncio.to_thread(
                stack,
                "exec",
                "-T",
                "redis",
                "redis-cli",
                "--raw",
                "ZSCORE",
                "fq:default:leases",
                ids[0],
            )
        )
        after = float(
            await asyncio.to_thread(
                stack, "exec", "-T", "redis", "redis-cli", "--raw", "EVAL", script, "0"
            )
        )
        assert before < deadline <= after + 3100
        await wait_terminal(api, ids, deadline_s=10)
