import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from forgequeue.config import Settings
from forgequeue.core.repo import Repository
from forgequeue.runtime import Runtime

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def service_urls():
    if os.getenv("TEST_DATABASE_URL") and os.getenv("TEST_REDIS_URL"):
        urls = os.environ["TEST_DATABASE_URL"], os.environ["TEST_REDIS_URL"]
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT,
            env={**os.environ, "DATABASE_URL": urls[0]},
            check=True,
            timeout=60,
        )
        yield urls
        return
    import docker
    from testcontainers.postgres import PostgresContainer
    from testcontainers.redis import RedisContainer

    try:
        client = docker.from_env()
        client.ping()
        client.close()
    except docker.errors.DockerException as exc:
        if os.getenv("REQUIRE_DOCKER") == "1":
            pytest.fail(f"Docker required but unavailable: {exc}")
        pytest.skip("Docker unavailable; real PostgreSQL/Redis integration was NOT RUN")
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        with RedisContainer("redis:7.4-alpine") as redis:
            urls = (
                pg.get_connection_url(),
                f"redis://{redis.get_container_host_ip()}:{redis.get_exposed_port(6379)}/0",
            )
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=ROOT,
                env={**os.environ, "DATABASE_URL": urls[0]},
                check=True,
                timeout=60,
            )
            yield urls


@pytest.fixture
async def runtime(service_urls):
    runtime = Runtime(
        Settings(
            database_url=service_urls[0],
            redis_url=service_urls[1],
            queues="default,other",
            lease_ms=600,
            heartbeat_ms=200,
            base_backoff_s=0,
            max_backoff_s=0,
            batch_size=100,
        )
    )
    async with runtime.engine.begin() as connection:
        await connection.execute(
            text("TRUNCATE job_attempts, jobs, workers, side_effects RESTART IDENTITY CASCADE")
        )
    await runtime.redis.flushdb()
    yield runtime
    await runtime.close()


@pytest.fixture
def repo(runtime):
    return Repository(runtime)
