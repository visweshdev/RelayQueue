import asyncio
import os
import subprocess
import sys

import httpx
import pytest

from relayqueue.api.main import create_app
from relayqueue.config import Settings
from relayqueue.runtime import Runtime


@pytest.fixture
async def client():
    runtime = Runtime(
        Settings(
            database_url="postgresql+asyncpg://unused@127.0.0.1:1/unused",
            redis_url="redis://127.0.0.1:1/0",
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url="http://test"
    ) as client:
        yield client
    await runtime.close()


async def test_health_and_readiness(client):
    assert (await client.get("/health")).json() == {"status": "ok"}
    assert (await client.get("/ready")).status_code == 503


@pytest.mark.parametrize("path", ["/v1/jobs", "/v1/workers", "/v1/queues/stats"])
async def test_authentication(client, path):
    result = await client.get(path)
    assert result.status_code == 401
    assert set(result.json()) == {"code", "message"}
    assert (await client.get(path, headers={"X-API-Key": "wrong"})).status_code == 401


async def test_metrics_and_unmatched(client):
    assert "http_request_duration_seconds" in (await client.get("/metrics")).text
    response = await client.get("/not-a-route")
    assert response.status_code == 404
    assert response.json()["code"] == "http_404"


async def test_metrics_aggregate_independent_api_processes(client, tmp_path, monkeypatch):
    directory = str(tmp_path / "metrics")
    os.mkdir(directory)
    environment = {**os.environ, "PROMETHEUS_MULTIPROC_DIR": directory}
    command = (
        "from relayqueue.obs.metrics import SUBMITTED; "
        "SUBMITTED.labels('multiproc-test', 'noop', '1').inc()"
    )
    for _ in range(2):
        await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-c", command],
            env=environment,
            check=True,
            timeout=15,
        )
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", directory)
    text = (await client.get("/metrics")).text
    assert 'fq_jobs_submitted_total{priority="1",queue="multiproc-test",task="noop"} 2.0' in text


async def test_streamed_body_limit(client):
    async def data():
        for _ in range(10):
            yield b"x" * 65536

    result = await client.post("/v1/jobs", content=data(), headers={"X-API-Key": "dev-key-1"})
    assert result.status_code == 413


async def test_invalid_list_arguments(client):
    result = await client.get("/v1/jobs?limit=101", headers={"X-API-Key": "dev-key-1"})
    assert result.status_code == 400
