import asyncio
import socket
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from forgequeue.api.schemas import JobCreate
from forgequeue.core.states import Status
from forgequeue.reaper.reaper import reap, update_gauges
from forgequeue.reaper.reconciler import reconcile
from forgequeue.worker.worker import Worker

pytestmark = pytest.mark.integration


async def wait_status(repo, identifier, status):
    async with asyncio.timeout(10):
        while True:
            job, _ = await repo.get(identifier)
            if job.status == status:
                return job
            await asyncio.sleep(0.02)


async def test_worker_loop_and_graceful_drain(repo):
    worker = Worker(repo.runtime)
    task = asyncio.create_task(worker.run())
    try:
        await asyncio.sleep(0.1)  # Exercise the empty-queue adaptive polling path.
        job, _ = await repo.submit(JobCreate(task="noop"))
        await wait_status(repo, job.id, Status.SUCCEEDED)
        await update_gauges(repo)
    finally:
        worker.stop.set()
        await asyncio.wait_for(task, 5)
    record = (await repo.worker_stats())[0]
    assert record["status"] == "stopped" and record["jobs_done"] == 1
    assert not record["alive"]


async def test_shutdown_grace_expiry_stops_handler_and_preserves_history(repo):
    repo.settings.shutdown_grace_s = 0.05
    worker = Worker(repo.runtime)
    job, _ = await repo.submit(JobCreate(task="sleep", payload={"seconds": 30}, max_attempts=1))
    task = asyncio.create_task(worker.run())
    try:
        await wait_status(repo, job.id, Status.RUNNING)
    finally:
        worker.stop.set()
        await asyncio.wait_for(task, 5)
    job, history = await repo.get(job.id)
    assert job.status == Status.DEAD
    assert history[0].error == "Worker shutdown grace expired"
    assert await repo.broker.owner(job.id) is None


async def test_running_worker_stops_when_lease_lost(repo):
    job, _ = await repo.submit(JobCreate(task="sleep", payload={"seconds": 30}))
    assert await repo.broker.claim("default", "w", "w:token") == job.id
    started = await repo.begin_attempt(job.id, "w", "w:token")
    worker = Worker(repo.runtime)
    execution = asyncio.create_task(worker.execute(started, "w:token"))
    await repo.runtime.redis.delete(f"fq:lease:{job.id}")
    await asyncio.wait_for(execution, 3)
    await reap(repo)
    current, history = await repo.get(job.id)
    assert current.status == Status.QUEUED
    assert history[0].outcome == "lease_expired"


async def test_publish_gap_after_committed_submission(repo, monkeypatch):
    original = repo.broker.sync

    async def unavailable(*args, **kwargs):
        raise RedisConnectionError("Injected publish outage")

    monkeypatch.setattr(repo.broker, "sync", unavailable)
    job, accepted = await repo.submit(JobCreate(task="noop"))
    assert accepted and (await repo.get(job.id))[0].status == Status.QUEUED
    monkeypatch.setattr(repo.broker, "sync", original)
    await reconcile(repo)
    assert await repo.broker.claim("default", "w", "t") == job.id


async def test_cancel_retrying_job_and_terminal_cleanup(repo):
    job, _ = await repo.submit(JobCreate(task="flaky", payload={"fail_rate": 1}))
    assert await repo.broker.claim("default", "w", "t") == job.id
    started = await repo.begin_attempt(job.id, "w", "t")
    await Worker(repo.runtime).execute(started, "t")
    assert (await repo.get(job.id))[0].status == Status.RETRYING
    assert (await repo.cancel(job.id)).status == Status.CANCELLED
    await repo.runtime.redis.zadd("fq:default:ready:0", {str(job.id): 0})
    await reconcile(repo)
    assert await repo.broker.claim("default", "w", "t2") is None


async def test_health_check_uses_real_worker_liveness(repo, monkeypatch):
    from forgequeue import health

    monkeypatch.setattr(health, "Runtime", lambda settings: repo.runtime)
    await repo.worker_heartbeat(socket.gethostname() + ":test")
    await health.check()


@pytest.mark.parametrize("wall_time", [-1_000_000_000, 1_000_000_000_000])
async def test_lease_ignores_client_clock_drift(repo, monkeypatch, wall_time):
    job, _ = await repo.submit(JobCreate(task="noop"))
    before = await repo.runtime.redis.time()
    monkeypatch.setattr("time.time", lambda: wall_time)
    assert await repo.broker.claim("default", "clock-worker", "clock-token") == job.id
    assert await repo.broker.heartbeat("default", job.id, "clock-token")
    deadline = await repo.runtime.redis.zscore("fq:default:leases", str(job.id))
    after = await repo.runtime.redis.time()
    before_ms = before[0] * 1000 + before[1] / 1000
    after_ms = after[0] * 1000 + after[1] / 1000
    assert before_ms + repo.settings.lease_ms <= deadline <= after_ms + repo.settings.lease_ms


async def test_ready_publish_wakes_worker_subscription(repo):
    worker = Worker(repo.runtime)
    notifications = asyncio.create_task(worker.notifications())
    channel = repo.broker.keys("default")[0] + ":notify"
    try:
        async with asyncio.timeout(5):
            while True:
                subscriptions = await repo.runtime.redis.pubsub_numsub(channel)
                if subscriptions[0][1]:
                    break
                await asyncio.sleep(0.01)
            await repo.submit(JobCreate(task="noop"))
            await worker.wakeups[0].wait()
    finally:
        worker.stop.set()
        notifications.cancel()
        await asyncio.gather(notifications, return_exceptions=True)


async def test_reconciliation_skips_finished_history_but_cleans_stray_indexes(repo):
    jobs = [(await repo.submit(JobCreate(task="noop")))[0] for _ in range(8)]
    for job in jobs:
        await repo.cancel(job.id)
    orphan = uuid4()
    for key in repo.broker.keys("default"):
        await repo.runtime.redis.zadd(key, {str(jobs[0].id): 0, str(orphan): 0})
    # No terminal history row needs recovery; stale indexes still get removed.
    assert await reconcile(repo) == 0
    for key in repo.broker.keys("default"):
        assert await repo.runtime.redis.zcard(key) == 0
