"""Durable state changes serialize on the job row. Never hold locks during execution."""

from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import structlog
from redis.exceptions import RedisError
from sqlalchemy import func, literal, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from relayqueue.api.schemas import JobCreate
from relayqueue.core.backoff import retry_delay
from relayqueue.core.cursors import decode_cursor, encode_cursor
from relayqueue.core.models import Attempt, Job, WorkerRecord
from relayqueue.core.states import TERMINAL, Status, transition
from relayqueue.obs import metrics
from relayqueue.runtime import Runtime
from relayqueue.worker.runner import Outcome

log = structlog.get_logger()


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


async def db_now(session: AsyncSession) -> datetime:
    return cast(datetime, (await session.execute(select(func.clock_timestamp()))).scalar_one())


def move(job: Job, target: Status, now: datetime, *, manual: bool = False) -> None:
    job.status = transition(job.status, target, manual=manual)
    job.updated_at = now


class Repository:
    def __init__(self, runtime: Runtime, allowed_queue: str | None = None) -> None:
        self.runtime = runtime
        self.allowed_queue = allowed_queue
        self.broker = runtime.broker
        self.settings = runtime.settings

    async def locked(self, session: AsyncSession, job_id: UUID) -> Job:
        job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None or (self.allowed_queue is not None and job.queue != self.allowed_queue):
            raise NotFound("Job not found")
        return job

    async def submit(self, spec: JobCreate) -> tuple[Job, bool]:
        if self.allowed_queue is not None and spec.queue != self.allowed_queue:
            raise NotFound("Queue not found")
        async with self.runtime.sessions.begin() as session:
            now = await db_now(session)
            run_at = spec.run_at or now
            values = spec.model_dump(exclude={"run_at"})
            values.update(
                id=uuid4(),
                run_at=run_at,
                created_at=now,
                updated_at=now,
                status=transition(None, Status.SCHEDULED if run_at > now else Status.QUEUED),
            )
            statement = (
                insert(Job)
                .values(**values)
                .on_conflict_do_nothing(
                    index_elements=[Job.queue, Job.idempotency_key],
                    index_where=Job.idempotency_key.is_not(None),
                )
                .returning(Job)
            )
            job = (await session.execute(statement)).scalar_one_or_none()
            created = job is not None
            if job is None:
                job = (
                    await session.execute(
                        select(Job).where(
                            Job.queue == spec.queue, Job.idempotency_key == spec.idempotency_key
                        )
                    )
                ).scalar_one()
        if created:
            metrics.SUBMITTED.labels(job.queue, job.task, job.priority).inc()
            log.info("job_submitted", job_id=str(job.id), queue=job.queue, task=job.task)
        await self.publish(job.id)
        return job, created

    async def publish(self, job_id: UUID) -> None:
        # Read current state under lock, not a stale object retained across a commit.
        try:
            async with self.runtime.sessions.begin() as session:
                job = await self.locked(session, job_id)
                await self.sync_locked(session, job)
        except RedisError:
            log.warning("publish_deferred", job_id=str(job_id))

    async def sync_locked(self, session: AsyncSession, job: Job) -> None:
        if job.status in TERMINAL:
            mode = "terminal"
        elif job.status == Status.QUEUED:
            mode = "queued"
        elif job.status in {Status.SCHEDULED, Status.RETRYING}:
            mode = "scheduled"
        else:
            if job.cancel_requested:
                await self.broker.request_cancel(job.id)
            return
        score_at = job.updated_at if mode == "queued" else job.run_at
        published = await self.broker.sync(
            job.queue, job.id, mode, job.priority, score_at.timestamp() * 1000
        )
        if published and mode == "queued" and job.attempt_seq:
            await session.execute(
                update(Attempt)
                .where(
                    Attempt.job_id == job.id,
                    Attempt.attempt_no == job.attempt_seq,
                    Attempt.requeued_at.is_(None),
                )
                .values(requeued_at=await db_now(session))
            )

    async def get(self, job_id: UUID) -> tuple[Job, list[Attempt]]:
        async with self.runtime.sessions() as session:
            job = await session.get(Job, job_id)
            if job is None or (self.allowed_queue is not None and job.queue != self.allowed_queue):
                raise NotFound("Job not found")
            history = list(
                (
                    await session.scalars(
                        select(Attempt).where(Attempt.job_id == job_id).order_by(Attempt.attempt_no)
                    )
                ).all()
            )
            return job, history

    async def list_jobs(
        self,
        *,
        limit: int,
        cursor: str | None = None,
        status: Status | None = None,
        queue: str | None = None,
        task: str | None = None,
    ) -> tuple[list[Job], str | None]:
        statement = select(Job).order_by(Job.created_at.desc(), Job.id.desc()).limit(limit + 1)
        if self.allowed_queue is not None:
            statement = statement.where(Job.queue == self.allowed_queue)
        if cursor:
            timestamp, identifier = decode_cursor(cursor)
            statement = statement.where(
                tuple_(Job.created_at, Job.id) < tuple_(literal(timestamp), literal(identifier))
            )
        for column, value in ((Job.status, status), (Job.queue, queue), (Job.task, task)):
            if value is not None:
                statement = statement.where(column == value)
        async with self.runtime.sessions() as session:
            jobs = list((await session.scalars(statement)).all())
        next_cursor = encode_cursor(jobs[-2].created_at, jobs[-2].id) if len(jobs) > limit else None
        return jobs[:limit], next_cursor

    async def cancel(self, job_id: UUID) -> Job:
        async with self.runtime.sessions.begin() as session:
            job = await self.locked(session, job_id)
            if job.status in TERMINAL:
                raise Conflict("Job already finished")
            now = await db_now(session)
            job.cancel_requested = True
            job.updated_at = now
            if job.status != Status.RUNNING:
                move(job, Status.CANCELLED, now)
                job.finished_at = now
        await self.publish(job.id)
        log.info("job_cancel_requested", job_id=str(job.id), queue=job.queue, task=job.task)
        return job

    async def retry(self, job_id: UUID) -> Job:
        async with self.runtime.sessions.begin() as session:
            job = await self.locked(session, job_id)
            if job.status != Status.DEAD:
                raise Conflict("Only dead jobs can be retried")
            now = await db_now(session)
            move(job, Status.QUEUED, now, manual=True)
            job.attempts = 0
            job.run_at = now
            job.result = job.last_error = job.locked_by = job.claim_token = None
            job.started_at = job.finished_at = None
            job.cancel_requested = False
        await self.publish(job_id)
        return job

    async def begin_attempt(self, job_id: UUID, worker_id: str, token: str) -> Job | None:
        async with self.runtime.sessions.begin() as session:
            job = await self.locked(session, job_id)
            now = await db_now(session)
            if job.status != Status.QUEUED or job.run_at > now or job.cancel_requested:
                return None
            if not await self.broker.heartbeat(job.queue, job.id, token):
                return None
            move(job, Status.RUNNING, now)
            job.attempts += 1
            job.attempt_seq += 1
            job.claim_token, job.locked_by, job.started_at = token, worker_id, now
            session.add(
                Attempt(
                    job_id=job.id, attempt_no=job.attempt_seq, worker_id=worker_id, started_at=now
                )
            )
        metrics.PICKUP.labels(job.queue, job.priority).observe(
            (now - job.created_at).total_seconds()
        )
        log.info(
            "job_started",
            job_id=str(job.id),
            worker_id=worker_id,
            attempt=job.attempt_seq,
            queue=job.queue,
            task=job.task,
        )
        return job

    async def heartbeat(self, job_id: UUID, token: str) -> tuple[bool, bool]:
        async with self.runtime.sessions.begin() as session:
            job = await self.locked(session, job_id)
            if job.status != Status.RUNNING or job.claim_token != token:
                return False, False
            valid = await self.broker.heartbeat(job.queue, job.id, token)
            return valid, job.cancel_requested

    async def finish(self, job_id: UUID, token: str, outcome: Outcome) -> bool:
        async with self.runtime.sessions.begin() as session:
            job = await self.locked(session, job_id)
            valid = job.status == Status.RUNNING and job.claim_token == token
            if valid:
                valid = await self.broker.heartbeat(job.queue, job.id, token)
            if not valid:
                metrics.DUPLICATES.labels(job.queue, job.task).inc()
                log.warning(
                    "stale_completion_discarded", job_id=str(job.id), queue=job.queue, task=job.task
                )
                return False
            now = await db_now(session)
            if job.cancel_requested:
                outcome = Outcome("cancelled", error="Cancellation acknowledged")
            await self.record_outcome(session, job, outcome, now)
            if job.locked_by:
                await session.execute(
                    update(WorkerRecord)
                    .where(WorkerRecord.id == job.locked_by)
                    .values(jobs_done=WorkerRecord.jobs_done + 1)
                )
            job.claim_token = job.locked_by = None
        # PostgreSQL outcome commits before lease deletion. Crash here is harmless.
        await self.broker.complete(job.queue, job.id, token)
        await self.publish(job_id)
        return True

    async def note_handler_finished(self, job_id: UUID, attempt_no: int) -> None:
        # Audit only: never authorizes a state transition or a stale result write.
        async with self.runtime.sessions.begin() as session:
            await session.execute(
                update(Attempt)
                .where(Attempt.job_id == job_id, Attempt.attempt_no == attempt_no)
                .values(handler_finished_at=await db_now(session))
            )

    async def record_outcome(
        self, session: AsyncSession, job: Job, outcome: Outcome, now: datetime
    ) -> None:
        attempt = (
            await session.execute(
                select(Attempt).where(
                    Attempt.job_id == job.id, Attempt.attempt_no == job.attempt_seq
                )
            )
        ).scalar_one()
        attempt.outcome, attempt.error, attempt.finished_at = outcome.kind, outcome.error, now
        attempt.duration_ms = int((now - attempt.started_at).total_seconds() * 1000)
        job.last_error = outcome.error
        if outcome.kind == "succeeded":
            target = Status.SUCCEEDED
            job.result = outcome.result
            attempt.handler_finished_at = now
        elif outcome.kind == "cancelled" or job.cancel_requested:
            target = Status.CANCELLED
        elif job.attempts >= job.max_attempts:
            target = Status.DEAD
        else:
            target = Status.RETRYING
            job.run_at = now + timedelta(
                seconds=retry_delay(
                    job.attempts, self.settings.base_backoff_s, self.settings.max_backoff_s
                )
            )
        move(job, target, now)
        if target in TERMINAL:
            job.finished_at = now
        metric_outcome = "failed" if target == Status.RETRYING else target.value
        metrics.COMPLETED.labels(job.queue, job.task, metric_outcome).inc()
        metrics.DURATION.labels(job.queue, job.task).observe(attempt.duration_ms / 1000)
        log.info(
            f"job_{target.value}",
            job_id=str(job.id),
            worker_id=job.locked_by,
            attempt=job.attempt_seq,
            queue=job.queue,
            task=job.task,
            error=outcome.error,
        )

    async def recover(self, job_id: UUID) -> bool:
        recovered = False
        async with self.runtime.sessions.begin() as session:
            job = await self.locked(session, job_id)
            if job.status == Status.RUNNING and await self.broker.owner(job.id) != job.claim_token:
                now = await db_now(session)
                await self.record_outcome(
                    session, job, Outcome("lease_expired", error="Execution lease lost"), now
                )
                if job.attempts < job.max_attempts and not job.cancel_requested:
                    # R2 requires immediate recovery after expiry, not another retry delay.
                    # Validate both edges; handler errors/timeouts still use full jitter.
                    move(job, Status.QUEUED, now)
                    job.run_at = now
                job.claim_token = job.locked_by = None
                recovered = True
                metrics.EXPIRED.labels(job.queue).inc()
                log.warning("lease_expired", job_id=str(job.id), queue=job.queue)
                log.info(
                    "job_recovered",
                    job_id=str(job.id),
                    queue=job.queue,
                    attempt=job.attempt_seq,
                    status=job.status,
                )
        await self.publish(job_id)
        return recovered

    async def promote(self) -> int:
        async with self.runtime.sessions.begin() as session:
            now = await db_now(session)
            jobs = list(
                (
                    await session.scalars(
                        select(Job)
                        .where(
                            Job.status.in_([Status.SCHEDULED, Status.RETRYING]), Job.run_at <= now
                        )
                        .order_by(Job.run_at)
                        .limit(self.settings.batch_size)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for job in jobs:
                move(job, Status.QUEUED, now)
        for job in jobs:
            await self.publish(job.id)
        return len(jobs)

    async def worker_heartbeat(self, worker_id: str, status: str = "active") -> None:
        async with self.runtime.sessions.begin() as session:
            now = await db_now(session)
            await session.execute(
                insert(WorkerRecord)
                .values(id=worker_id, last_heartbeat=now, started_at=now, status=status)
                .on_conflict_do_update(
                    index_elements=[WorkerRecord.id], set_={"last_heartbeat": now, "status": status}
                )
            )
        if status == "stopped":
            await self.runtime.redis.hdel("fq:workers", worker_id)
        else:
            await self.runtime.redis.hset("fq:workers", worker_id, str(now.timestamp()))

    async def worker_stats(self) -> list[dict[str, Any]]:
        async with self.runtime.sessions() as session:
            now = await db_now(session)
            records = list((await session.scalars(select(WorkerRecord))).all())
        return [
            {
                "id": w.id,
                "started_at": w.started_at,
                "last_heartbeat": w.last_heartbeat,
                "jobs_done": w.jobs_done,
                "status": w.status,
                "alive": w.status != "stopped"
                and (now - w.last_heartbeat).total_seconds() < self.settings.lease_ms / 1000,
            }
            for w in records
        ]

    async def queue_stats(self) -> list[dict[str, Any]]:
        async with self.runtime.sessions() as session:
            now = await db_now(session)
            rows = (
                await session.execute(
                    select(
                        Job.queue, Job.status, Job.priority, func.count(), func.min(Job.updated_at)
                    )
                    .where(
                        Job.queue == self.allowed_queue
                        if self.allowed_queue is not None
                        else literal(True)
                    )
                    .group_by(Job.queue, Job.status, Job.priority)
                )
            ).all()
        return [
            {
                "queue": q,
                "status": s,
                "priority": p,
                "count": n,
                "oldest_ready_age_s": max(0, (now - oldest).total_seconds())
                if s == Status.QUEUED
                else None,
            }
            for q, s, p, n, oldest in rows
        ]
