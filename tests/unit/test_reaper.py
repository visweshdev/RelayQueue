import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from relayqueue.config import Settings
from relayqueue.reaper import reaper


async def test_slow_reconstruction_cannot_block_recovery_or_scheduler(monkeypatch):
    scanning, scheduled, recovered = asyncio.Event(), asyncio.Event(), asyncio.Event()
    stop = asyncio.Event()

    async def slow_scan(repo):
        scanning.set()
        await asyncio.Event().wait()

    async def schedule(repo):
        scheduled.set()

    async def recover(repo):
        recovered.set()

    monkeypatch.setattr(reaper, "reconcile", slow_scan)
    monkeypatch.setattr(reaper, "promote_due", schedule)
    monkeypatch.setattr(reaper, "reap", recover)
    monkeypatch.setattr(reaper, "update_gauges", AsyncMock())
    task = asyncio.create_task(reaper.run_loops(SimpleNamespace(settings=Settings()), stop))
    try:
        async with asyncio.timeout(2):
            await scanning.wait()
            await scheduled.wait()
            await recovered.wait()
    finally:
        stop.set()
        await asyncio.wait_for(task, 2)


async def test_periodic_loop_recovers_after_dependency_failure():
    stop = asyncio.Event()
    calls = 0

    async def action():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("temporary outage")
        stop.set()

    await asyncio.wait_for(reaper.periodic("test", action, 0.01, stop), 2)
    assert calls == 2
