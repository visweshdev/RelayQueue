import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from forgequeue.api.schemas import JobCreate
from forgequeue.core.models import Attempt, Job, utcnow
from forgequeue.core.states import Status
from forgequeue.reaper.reconciler import reconcile
from forgequeue.reaper.scheduler import promote_due
from forgequeue.worker.runner import Outcome
from forgequeue.worker.worker import Worker

pytestmark = pytest.mark.integration


async def claim(repo, worker_id="test-worker"):
    token = f"{worker_id}:{uuid4()}"
    identifier = await repo.broker.claim("default", worker_id, token)
    assert identifier is not None
    job = await repo.begin_attempt(identifier, worker_id, token)
    assert job is not None
    return job, token


async def execute(repo):
    job, token = await claim(repo)
    await Worker(repo.runtime).execute(job, token)
    return (await repo.get(job.id))[0]


async def test_submit_and_execute(repo):
    job, created = await repo.submit(JobCreate(task="noop"))
    assert created and job.status == Status.QUEUED
    result = await execute(repo)
    assert result.status == Status.SUCCEEDED and result.result == {"ok": True}
    _, history = await repo.get(job.id)
    assert len(history) == 1 and history[0].outcome == "succeeded"
    assert history[0].handler_finished_at is not None


async def test_concurrent_idempotency(repo):
    results = await asyncio.gather(
        *[repo.submit(JobCreate(task="noop", idempotency_key="same")) for _ in range(20)]
    )
    assert len({job.id for job, _ in results}) == 1
    assert sum(created for _, created in results) == 1
    other, created = await repo.submit(
        JobCreate(task="noop", queue="other", idempotency_key="same")
    )
    assert created and other.id != results[0][0].id


async def test_priority_and_starvation_guard(repo):
    high = [(await repo.submit(JobCreate(task="noop", priority=0)))[0] for _ in range(11)]
    low = (await repo.submit(JobCreate(task="noop", priority=2)))[0]
    order = []
    for _ in range(10):
        job, token = await claim(repo)
        order.append(job.id)
        await repo.finish(job.id, token, Outcome("succeeded", {}))
    assert order[:9] == [job.id for job in high[:9]]
    assert order[9] == low.id


async def test_delayed_job(repo):
    job, _ = await repo.submit(JobCreate(task="noop", run_at=utcnow() + timedelta(seconds=0.4)))
    assert job.status == Status.SCHEDULED
    assert await repo.broker.claim("default", "w", "token") is None
    assert await promote_due(repo) == 0
    await asyncio.sleep(0.45)
    assert await promote_due(repo) == 1
    assert (await execute(repo)).status == Status.SUCCEEDED


async def test_retries_dead_and_manual_history(repo):
    original, _ = await repo.submit(
        JobCreate(task="flaky", payload={"fail_rate": 1}, max_attempts=3)
    )
    for attempt in range(1, 4):
        job = await execute(repo)
        assert job.attempts == attempt
        assert job.status == (Status.DEAD if attempt == 3 else Status.RETRYING)
        await promote_due(repo)
    _, history = await repo.get(original.id)
    assert [a.attempt_no for a in history] == [1, 2, 3]
    job = await repo.retry(original.id)
    assert job.attempts == 0 and job.attempt_seq == 3
    # A manual rerun of the same deterministic failing payload is still a real rerun.
    job, token = await claim(repo)
    assert job.attempts == 1 and job.attempt_seq == 4
    await repo.finish(job.id, token, Outcome("succeeded", {"repaired": True}))
    _, history = await repo.get(original.id)
    assert [a.attempt_no for a in history] == [1, 2, 3, 4]


@pytest.mark.parametrize("scheduled", [False, True])
async def test_cancel_before_execution(repo, scheduled):
    job, _ = await repo.submit(
        JobCreate(task="noop", run_at=utcnow() + timedelta(seconds=30) if scheduled else None)
    )
    cancelled = await repo.cancel(job.id)
    await reconcile(repo)
    assert cancelled.status == Status.CANCELLED
    assert await repo.broker.claim("default", "w", "t") is None


async def test_cancel_running_stops_execution(repo):
    original, _ = await repo.submit(JobCreate(task="sleep", payload={"seconds": 30}))
    job, token = await claim(repo)
    execution = asyncio.create_task(Worker(repo.runtime).execute(job, token))
    await asyncio.sleep(0.02)
    requested = await repo.cancel(job.id)
    assert requested.status == Status.RUNNING and requested.cancel_requested
    await asyncio.wait_for(execution, timeout=2)
    job, history = await repo.get(original.id)
    assert job.status == Status.CANCELLED and history[0].outcome == "cancelled"


async def test_timeout_and_lease_refresh(repo):
    await repo.submit(JobCreate(task="sleep", payload={"seconds": 2}, timeout_s=1, max_attempts=1))
    job = await execute(repo)
    _, history = await repo.get(job.id)
    assert job.status == Status.DEAD
    assert history[0].outcome == "timed_out"


async def test_late_completion_cannot_overwrite_successor(repo):
    await repo.submit(JobCreate(task="noop"))
    old, token = await claim(repo)
    await repo.runtime.redis.delete(f"fq:lease:{old.id}")
    assert await repo.recover(old.id)
    await promote_due(repo)
    newer, new_token = await claim(repo)
    assert not await repo.broker.heartbeat("default", old.id, token)
    assert not await repo.broker.complete("default", old.id, token)
    assert not await repo.finish(old.id, token, Outcome("succeeded", {"old": True}))
    assert await repo.broker.owner(newer.id) == new_token
    assert await repo.finish(newer.id, new_token, Outcome("succeeded", {"new": True}))
    result, history = await repo.get(old.id)
    assert result.result == {"new": True}
    assert [a.outcome for a in history] == ["lease_expired", "succeeded"]


@pytest.mark.parametrize(
    "stage", ["before_claim", "after_claim", "after_begin", "after_handler", "after_commit"]
)
async def test_crash_windows(repo, stage):
    job, _ = await repo.submit(JobCreate(task="noop"))
    token = "dead-worker:token"
    if stage != "before_claim":
        assert await repo.broker.claim("default", "dead-worker", token) == job.id
    if stage in {"after_begin", "after_handler", "after_commit"}:
        started = await repo.begin_attempt(job.id, "dead-worker", token)
        assert started is not None
    if stage == "after_handler":
        await repo.note_handler_finished(job.id, 1)
    if stage == "after_commit":
        await repo.finish(job.id, token, Outcome("succeeded", {"ok": True}))
        # Simulate cleanup not occurring: a terminal ID remains in a ready index.
        await repo.runtime.redis.zadd("fq:default:ready:1", {str(job.id): 0})
    else:
        await repo.runtime.redis.delete(f"fq:lease:{job.id}")
    await reconcile(repo)
    await promote_due(repo)
    if stage == "after_commit":
        assert await repo.broker.claim("default", "new", "new") is None
    else:
        assert (await execute(repo)).status == Status.SUCCEEDED
    result, _ = await repo.get(job.id)
    assert result.status == Status.SUCCEEDED


async def test_redis_index_loss_rebuild(repo):
    ready, _ = await repo.submit(JobCreate(task="noop"))
    scheduled, _ = await repo.submit(JobCreate(task="noop", run_at=utcnow() + timedelta(hours=1)))
    await repo.runtime.redis.flushdb()
    await reconcile(repo)
    assert await repo.runtime.redis.zscore("fq:default:ready:1", str(ready.id)) is not None
    assert await repo.runtime.redis.zscore("fq:default:scheduled", str(scheduled.id)) is not None
    assert (await execute(repo)).status == Status.SUCCEEDED


async def test_concurrent_recovery_does_not_create_multiple_attempts(repo):
    await repo.submit(JobCreate(task="noop"))
    job, _ = await claim(repo)
    await repo.runtime.redis.flushdb()
    recovered = await asyncio.gather(*[repo.recover(job.id) for _ in range(10)])
    assert sum(recovered) == 1
    await promote_due(repo)
    assert (await execute(repo)).status == Status.SUCCEEDED
    assert len((await repo.get(job.id))[1]) == 2


async def test_reconcile_during_claim_does_not_duplicate(repo):
    job, _ = await repo.submit(JobCreate(task="noop"))
    assert await repo.broker.claim("default", "w", "token") == job.id
    await asyncio.gather(*[repo.publish(job.id) for _ in range(10)])
    assert await repo.broker.claim("default", "other", "different") is None
    assert await repo.begin_attempt(job.id, "w", "token") is not None


async def test_one_thousand_jobs_eight_claimants(repo):
    semaphore = asyncio.Semaphore(16)

    async def submit():
        async with semaphore:
            return (await repo.submit(JobCreate(task="noop")))[0].id

    async with asyncio.timeout(180):
        identifiers = await asyncio.gather(*[submit() for _ in range(1000)])

        async def consume(worker_id):
            seen = []
            while True:
                token = f"{worker_id}:{uuid4()}"
                identifier = await repo.broker.claim("default", worker_id, token)
                if identifier is None:
                    return seen
                job = await repo.begin_attempt(identifier, worker_id, token)
                assert job is not None
                assert job.attempts == 1
                seen.append(identifier)
                await repo.finish(identifier, token, Outcome("succeeded", {"ok": True}))

        # Longer leases avoid turning database contention into a lease-expiry experiment.
        repo.broker.lease_ms = 30000
        results = await asyncio.gather(*[consume(f"worker-{i}") for i in range(8)])
    flattened = [identifier for result in results for identifier in result]
    assert len(flattened) == len(set(flattened)) == 1000
    assert set(flattened) == set(identifiers)
    async with repo.runtime.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Attempt)) == 1000


async def test_pagination_timestamp_ties(repo):
    jobs = [(await repo.submit(JobCreate(task="noop")))[0] for _ in range(7)]
    async with repo.runtime.sessions.begin() as session:
        await session.execute(update(Job).values(created_at=utcnow()))
    seen, cursor = [], None
    while True:
        page, cursor = await repo.list_jobs(limit=2, cursor=cursor)
        seen.extend(job.id for job in page)
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == len(jobs)
    assert seen == sorted([job.id for job in jobs], reverse=True)
