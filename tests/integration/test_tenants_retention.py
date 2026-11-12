import hashlib
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select, update

from relayqueue.api.main import create_app
from relayqueue.api.schemas import JobCreate
from relayqueue.core.models import Job
from relayqueue.core.repo import Repository, db_now
from relayqueue.core.states import Status
from relayqueue.retention import prune

pytestmark = pytest.mark.integration


async def test_tenants_cannot_read_or_mutate_other_queues(runtime):
    runtime.settings.tenant_keys = {
        hashlib.sha256(b"alpha-token").hexdigest(): "default",
        hashlib.sha256(b"beta-token").hexdigest(): "other",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url="http://test"
    ) as client:
        alpha = {"X-API-Key": "alpha-token"}
        beta = {"X-API-Key": "beta-token"}
        spec = {"task": "noop", "queue": "default", "idempotency_key": "same"}
        a = await client.post("/v1/jobs", json=spec, headers=alpha)
        b = await client.post("/v1/jobs", json={**spec, "queue": "other"}, headers=beta)
        assert a.status_code == b.status_code == 201
        assert a.json()["id"] != b.json()["id"]
        identifier = a.json()["id"]
        assert (await client.get(f"/v1/jobs/{identifier}", headers=beta)).status_code == 404
        for action in ("cancel", "retry"):
            assert (
                await client.post(f"/v1/jobs/{identifier}/{action}", headers=beta)
            ).status_code == 404
        assert (await client.post("/v1/jobs", json=spec, headers=beta)).status_code == 404
        assert (await client.get("/v1/jobs?queue=default", headers=beta)).json()["items"] == []
        items = (await client.get("/v1/jobs", headers=beta)).json()["items"]
        assert [item["id"] for item in items] == [b.json()["id"]]
        stats = (await client.get("/v1/queues/stats", headers=beta)).json()
        assert stats and all(row["queue"] == "other" for row in stats)
        assert (await client.get("/v1/workers", headers=beta)).status_code == 403
        assert (await client.get("/v1/session", headers=alpha)).json() == {"queue": "default"}
        assert (await client.get("/v1/jobs", headers={"X-API-Key": "dev-key-1"})).status_code == 401
        assert (await client.get("/v1/jobs")).status_code == 401
        assert (
            await client.post(f"/v1/jobs/{identifier}/cancel", headers=alpha)
        ).status_code == 202


async def test_retention_preserves_active_dead_and_recent_jobs(runtime):
    repo = Repository(runtime)
    jobs = [await repo.submit(JobCreate(task="noop")) for _ in range(5)]
    identifiers = [job.id for job, _ in jobs]
    async with runtime.sessions.begin() as session:
        now = await db_now(session)
        for identifier, status, age in zip(
            identifiers,
            [Status.SUCCEEDED, Status.CANCELLED, Status.DEAD, Status.RUNNING, Status.SUCCEEDED],
            [60, 60, 60, 60, 1],
            strict=True,
        ):
            await session.execute(
                update(Job)
                .where(Job.id == identifier)
                .values(status=status, finished_at=now - timedelta(days=age))
            )
    assert await prune(runtime, 30, 100, False) == 2
    assert await prune(runtime, 30, 1, True) == 1
    assert await prune(runtime, 30, 100, True) == 1
    async with runtime.sessions() as session:
        remaining = set(await session.scalars(select(Job.id)))
    assert remaining == set(identifiers[2:])
    with pytest.raises(ValueError):
        await prune(runtime, 0, 100, True)
