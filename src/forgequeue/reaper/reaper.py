import asyncio
import signal
import time
from collections.abc import Awaitable, Callable

import structlog
from prometheus_client import start_http_server

from forgequeue.config import Settings
from forgequeue.core.repo import Repository
from forgequeue.core.states import Status
from forgequeue.obs import metrics
from forgequeue.obs.logging import configure_logging
from forgequeue.reaper.reconciler import reconcile
from forgequeue.reaper.scheduler import promote_due
from forgequeue.runtime import Runtime

log = structlog.get_logger()


async def reap(repo: Repository) -> None:
    for queue in repo.settings.queue_names:
        for job_id in await repo.broker.expired(queue, repo.settings.batch_size):
            await repo.recover(job_id)
    # Redis FLUSH/restart removes expiry indexes too: scan durable running rows.
    await reconcile(repo, running_only=True)


async def update_gauges(repo: Repository) -> None:
    states = {
        Status.QUEUED: "ready",
        Status.SCHEDULED: "scheduled",
        Status.RETRYING: "scheduled",
        Status.RUNNING: "running",
    }
    for queue in repo.settings.queue_names:
        for priority in range(3):
            for state in set(states.values()):
                metrics.DEPTH.labels(queue, priority, state).set(0)
    counts: dict[tuple[str, int, str], int] = {}
    for row in await repo.queue_stats():
        if row["status"] in states:
            key = row["queue"], row["priority"], states[row["status"]]
            counts[key] = counts.get(key, 0) + row["count"]
    for (queue, priority, state), count in counts.items():
        metrics.DEPTH.labels(queue, priority, state).set(count)
    workers = await repo.worker_stats()
    metrics.ACTIVE.set(sum(w["alive"] for w in workers))
    stale = [w["id"] for w in workers if not w["alive"]]
    if stale:
        await repo.runtime.redis.hdel("fq:workers", *stale)


async def periodic(
    name: str, action: Callable[[], Awaitable[object]], interval: float, stop: asyncio.Event
) -> None:
    retry = 0.1
    while not stop.is_set():
        started = time.monotonic()
        try:
            await action()
            retry = 0.1
            delay = max(0, interval - (time.monotonic() - started))
        except Exception as exc:
            log.warning("reaper_reconnecting", loop=name, error=type(exc).__name__)
            delay = retry
            retry = min(5, retry * 2)
        try:
            await asyncio.wait_for(stop.wait(), delay)
        except TimeoutError:
            pass


async def run_loops(repo: Repository, stop: asyncio.Event) -> None:
    # Long index reconstruction must not postpone lease recovery or scheduling.
    async with asyncio.TaskGroup() as group:
        tasks = [
            group.create_task(
                periodic(
                    "reconcile", lambda: reconcile(repo), repo.settings.reconcile_interval_s, stop
                )
            ),
            group.create_task(
                periodic(
                    "schedule",
                    lambda: promote_due(repo),
                    repo.settings.scheduler_interval_ms / 1000,
                    stop,
                )
            ),
            group.create_task(
                periodic("reap", lambda: reap(repo), repo.settings.reaper_interval_ms / 1000, stop)
            ),
            group.create_task(
                periodic(
                    "gauges",
                    lambda: update_gauges(repo),
                    repo.settings.reaper_interval_ms / 1000,
                    stop,
                )
            ),
        ]
        await stop.wait()
        for task in tasks:
            task.cancel()


async def serve() -> None:
    configure_logging()
    runtime = Runtime(Settings())
    repo = Repository(runtime)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    server, thread = start_http_server(runtime.settings.metrics_port)
    try:
        await run_loops(repo, stop)
    finally:
        await runtime.close()
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(timeout=2)


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
