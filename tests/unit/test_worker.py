from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from relayqueue.config import Settings
from relayqueue.worker.worker import Worker


@pytest.mark.parametrize("stale_first_claim", [False, True])
async def test_worker_drains_available_work_without_idle_wait(stale_first_claim):
    """A backlog, including a stale index entry, must not incur polling delays."""
    identifiers = [uuid4() for _ in range(3)]
    broker = SimpleNamespace(claim=AsyncMock(side_effect=identifiers), complete=AsyncMock())
    runtime = SimpleNamespace(settings=Settings(), broker=broker)
    worker = Worker(runtime)
    jobs = [SimpleNamespace(id=identifier) for identifier in identifiers]
    worker.repo = SimpleNamespace(
        begin_attempt=AsyncMock(side_effect=[None if stale_first_claim else jobs[0], *jobs[1:]])
    )
    completed = []

    async def execute(job, token):
        completed.append(job.id)
        if job.id == identifiers[-1]:
            worker.stop.set()

    worker.execute = execute
    worker.wakeups[0].wait = AsyncMock(side_effect=AssertionError("Backlog incurred idle wait"))
    await worker.slot(0)
    assert completed == identifiers[int(stale_first_claim) :]
    assert broker.complete.await_count == int(stale_first_claim)
    worker.wakeups[0].wait.assert_not_called()
