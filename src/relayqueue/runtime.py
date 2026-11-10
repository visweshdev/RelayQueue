from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from relayqueue.broker.redis_broker import Broker
from relayqueue.config import Settings


class Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=0,
            pool_timeout=5,
            connect_args={
                "timeout": 5,
                "command_timeout": 10,
                "server_settings": {"idle_in_transaction_session_timeout": "15000"},
            },
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.redis = Redis.from_url(
            settings.redis_url, decode_responses=True, socket_connect_timeout=3, socket_timeout=3
        )
        self.broker = Broker(self.redis, settings.lease_ms)

    async def ready(self) -> None:
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await self.redis.ping()

    async def close(self) -> None:
        await self.redis.aclose()
        await self.engine.dispose()
