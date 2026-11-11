"""Bounded operator-only retention. Dry run unless --apply is supplied."""

import argparse
import asyncio
from datetime import timedelta

from sqlalchemy import delete, select

from relayqueue.config import Settings
from relayqueue.core.models import Job
from relayqueue.core.repo import db_now
from relayqueue.core.states import Status
from relayqueue.runtime import Runtime


async def prune(runtime: Runtime, days: int, limit: int, apply: bool) -> int:
    if days < 1 or not 1 <= limit <= 5000:
        raise ValueError("Retention needs at least one day and a batch of 1-5000")
    async with runtime.sessions.begin() as session:
        cutoff = await db_now(session) - timedelta(days=days)
        identifiers = list(
            await session.scalars(
                select(Job.id)
                .where(
                    Job.status.in_([Status.SUCCEEDED, Status.CANCELLED]),
                    Job.finished_at < cutoff,
                )
                .order_by(Job.finished_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        if apply and identifiers:
            await session.execute(delete(Job).where(Job.id.in_(identifiers)))
        return len(identifiers)


async def run(days: int, limit: int, apply: bool) -> None:
    runtime = Runtime(Settings())
    try:
        count = await prune(runtime, days, limit, apply)
        print(f"{'Deleted' if apply else 'Would delete'} {count} completed/cancelled jobs")
    finally:
        await runtime.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.days, args.limit, args.apply))


if __name__ == "__main__":
    main()
