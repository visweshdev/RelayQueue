from uuid import UUID

import structlog
from sqlalchemy import select

from relayqueue.core.models import Job
from relayqueue.core.repo import NotFound, Repository
from relayqueue.core.states import TERMINAL, Status

log = structlog.get_logger()


async def reconcile(repo: Repository, *, running_only: bool = False) -> int:
    cursor: UUID | None = None
    count = 0
    while True:
        async with repo.runtime.sessions() as session:
            query = select(Job.id).order_by(Job.id).limit(repo.settings.batch_size)
            if running_only:
                query = query.where(Job.status == Status.RUNNING)
            else:
                query = query.where(Job.status.not_in(TERMINAL))
            if cursor:
                query = query.where(Job.id > cursor)
            ids = list((await session.scalars(query)).all())
        if not ids:
            break
        for job_id in ids:
            await repo.recover(job_id)
            count += 1
        cursor = ids[-1]
    if not running_only:
        # Completed history is not a recovery backlog. Inspect only Redis members
        # for stale terminal entries, including scheduled cancellations whose
        # commit succeeded while Redis cleanup was unavailable.
        for queue in repo.settings.queue_names:
            for key in repo.broker.keys(queue):
                async for member, _ in repo.runtime.redis.zscan_iter(
                    key, count=repo.settings.batch_size
                ):
                    job_id = UUID(member)
                    try:
                        async with repo.runtime.sessions.begin() as session:
                            job = await repo.locked(session, job_id)
                            if job.status in TERMINAL:
                                await repo.sync_locked(session, job)
                    except NotFound:
                        await repo.broker.sync(queue, job_id, "terminal", 0, 0)
        log.info("redis_reconciliation_completed", jobs_scanned=count)
    return count
