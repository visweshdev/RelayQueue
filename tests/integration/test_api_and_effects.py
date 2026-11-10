import asyncio
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, update

from relayqueue.api.main import create_app
from relayqueue.core.effects import apply_once
from relayqueue.core.models import SideEffect, WorkerRecord
from relayqueue.core.repo import Repository
from relayqueue.reaper.reaper import update_gauges

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(runtime):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://test",
        headers={"X-API-Key": "dev-key-1"},
    ) as client:
        yield client


async def test_api_codes_and_filters(client, repo):
    assert (await client.get("/ready")).status_code == 200
    first = await client.post("/v1/jobs", json={"task": "noop", "idempotency_key": "one"})
    assert first.status_code == 201
    second = await client.post("/v1/jobs", json={"task": "noop", "idempotency_key": "one"})
    assert second.status_code == 200 and first.json()["id"] == second.json()["id"]
    identifier = first.json()["id"]
    assert (await client.get(f"/v1/jobs/{identifier}")).json()["history"] == []
    assert (await client.get(f"/v1/jobs/{uuid4()}")).status_code == 404
    assert (await client.post(f"/v1/jobs/{identifier}/retry")).status_code == 409
    assert (await client.post(f"/v1/jobs/{identifier}/cancel")).status_code == 202
    assert (await client.post(f"/v1/jobs/{identifier}/cancel")).status_code == 409
    assert (
        len((await client.get("/v1/jobs?status=cancelled&queue=default&task=noop")).json()["items"])
        == 1
    )
    assert (await client.get("/v1/jobs?cursor=bad")).status_code == 400
    assert (
        await client.post("/v1/jobs", json={"task": "noop", "queue": "unconfigured"})
    ).status_code == 400
    assert (await client.post("/v1/jobs", json={"task": "missing"})).status_code == 422
    assert (
        await client.post("/v1/jobs", json={"task": "noop", "payload": {"large": "a" * 65537}})
    ).status_code == 413
    assert (await client.get("/v1/queues/stats")).status_code == 200
    await repo.worker_heartbeat("worker")
    assert (await client.get("/v1/workers")).json()[0]["alive"]
    await update_gauges(repo)
    assert "fq_workers_active 1.0" in (await client.get("/metrics")).text


async def test_token_bucket_burst_refill_and_isolation(runtime):
    results = await asyncio.gather(*[runtime.broker.rate_limit("key", 2) for _ in range(3)])
    assert sum(results) == 2
    assert await runtime.broker.rate_limit("other-key", 2)
    await asyncio.sleep(0.55)
    assert await runtime.broker.rate_limit("key", 2)


async def test_api_rate_limit(client, runtime):
    runtime.settings.rate_limit_per_s = 1
    assert (await client.post("/v1/jobs", json={"task": "noop"})).status_code == 201
    response = await client.post("/v1/jobs", json={"task": "noop"})
    assert response.status_code == 429 and response.headers["retry-after"] == "1"


async def test_effect_deduplication_and_rollback(runtime):
    repo = Repository(runtime)
    await repo.worker_heartbeat("ledger-example")

    async def increment(session):
        await session.execute(
            update(WorkerRecord)
            .where(WorkerRecord.id == "ledger-example")
            .values(jobs_done=WorkerRecord.jobs_done + 1)
        )
        return {"incremented": True}

    async def apply():
        async with runtime.sessions.begin() as session:
            return await apply_once(session, "credit:1", increment)

    values = await asyncio.gather(*[apply() for _ in range(10)])
    assert all(value == {"incremented": True} for value in values)
    async with runtime.sessions() as session:
        assert (await session.get(WorkerRecord, "ledger-example")).jobs_done == 1
    with pytest.raises(RuntimeError):
        async with runtime.sessions.begin() as session:
            await apply_once(session, "credit:rolled-back", increment)
            raise RuntimeError("Crash before commit")
    async with runtime.sessions() as session:
        assert await session.get(SideEffect, "credit:rolled-back") is None
        assert await session.scalar(select(WorkerRecord.jobs_done)) == 1
