from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from relayqueue.core.models import SideEffect


async def apply_once(
    session: AsyncSession, key: str, effect: Callable[[AsyncSession], Awaitable[dict[str, Any]]]
) -> dict[str, Any]:
    """Deduplicate database effects in the SAME caller-owned transaction.

    The callback must use this session; HTTP/email/file effects are not transactional.
    PostgreSQL's unique-key conflict waits for a competing transaction to commit or roll back.
    """
    inserted = await session.scalar(
        insert(SideEffect)
        .values(key=key, value={})
        .on_conflict_do_nothing()
        .returning(SideEffect.key)
    )
    row = await session.get(SideEffect, key)
    if row is None:
        raise RuntimeError("Side-effect record missing")
    if inserted is not None:
        row.value = await effect(session)
        await session.flush()
    return row.value
