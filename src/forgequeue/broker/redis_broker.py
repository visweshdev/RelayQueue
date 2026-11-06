from hashlib import sha256
from pathlib import Path
from typing import cast
from uuid import UUID

from redis.asyncio import Redis


class Broker:
    def __init__(self, redis: Redis, lease_ms: int = 30_000) -> None:
        self.redis = redis
        self.lease_ms = lease_ms
        directory = Path(__file__).parent / "lua"
        self.scripts = {
            p.stem: redis.register_script(p.read_text()) for p in directory.glob("*.lua")
        }

    @staticmethod
    def keys(queue: str) -> list[str]:
        prefix = f"fq:{queue}"
        return [f"{prefix}:ready:{i}" for i in range(3)] + [
            f"{prefix}:scheduled",
            f"{prefix}:leases",
        ]

    async def claim(self, queue: str, worker: str, token: str) -> UUID | None:
        keys = self.keys(queue)
        result = await self.scripts["claim"](
            keys=keys[:3] + [keys[4], f"fq:claims:{worker}"], args=[self.lease_ms, token]
        )
        return UUID(str(result)) if result else None

    async def heartbeat(self, queue: str, job_id: UUID, token: str) -> bool:
        return bool(
            await self.scripts["heartbeat"](
                keys=[f"fq:lease:{job_id}", self.keys(queue)[4]],
                args=[str(job_id), token, self.lease_ms],
            )
        )

    async def complete(self, queue: str, job_id: UUID, token: str) -> bool:
        return bool(
            await self.scripts["complete"](
                keys=[f"fq:lease:{job_id}", self.keys(queue)[4]], args=[str(job_id), token]
            )
        )

    async def owner(self, job_id: UUID) -> str | None:
        return cast(str | None, await self.redis.get(f"fq:lease:{job_id}"))

    async def sync(self, queue: str, job_id: UUID, mode: str, priority: int, score: float) -> bool:
        return bool(
            await self.scripts["sync"](
                keys=self.keys(queue) + [f"fq:lease:{job_id}", f"fq:cancel:{job_id}"],
                args=[str(job_id), mode, priority, score],
            )
        )

    async def request_cancel(self, job_id: UUID) -> None:
        await self.redis.set(f"fq:cancel:{job_id}", "1", ex=3600)

    async def rate_limit(self, api_key: str, rate: int) -> bool:
        digest = sha256(api_key.encode()).hexdigest()
        return bool(await self.scripts["ratelimit"](keys=[f"fq:rate:{digest}"], args=[rate, rate]))

    async def expired(self, queue: str, limit: int) -> list[UUID]:
        result = await self.scripts["expired"](keys=[self.keys(queue)[4]], args=[limit])
        return [UUID(value) for value in result]
