"""A database-only side effect: persist one notification receipt per logical key."""

import asyncio
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from forgequeue.config import Settings
from forgequeue.core.effects import apply_once
from forgequeue.runtime import Runtime


async def receipt(session: AsyncSession) -> dict[str, Any]:
    # The ledger value is the durable effect. This does not send email or call HTTP.
    return {"recipient": "demo@example.test", "notification": "welcome"}


async def main() -> None:
    runtime = Runtime(Settings())
    try:
        for _ in range(2):
            async with runtime.sessions.begin() as session:
                result = await apply_once(session, "notification:demo:welcome", receipt)
                print(json.dumps(result))
    finally:
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
