import asyncio
import contextlib
import os
import signal
import socket
from uuid import uuid4

import structlog
from prometheus_client import start_http_server

from relayqueue.config import Settings
from relayqueue.core.models import Job
from relayqueue.core.repo import Repository
from relayqueue.obs.logging import configure_logging
from relayqueue.runtime import Runtime
from relayqueue.worker.runner import Outcome, run_handler

log = structlog.get_logger()


class Worker:
    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self.repo = Repository(runtime)
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
        self.stop = asyncio.Event()
        self.wakeups = [asyncio.Event() for _ in range(runtime.settings.worker_concurrency)]

    async def execute(self, job: Job, token: str) -> None:
        execution = asyncio.create_task(
            run_handler(job.task, job.payload, job.timeout_s, self.runtime.settings)
        )
        try:
            while True:
                done, _ = await asyncio.wait(
                    {execution}, timeout=self.runtime.settings.heartbeat_ms / 1000
                )
                if done:
                    if execution.result().kind == "succeeded":
                        await self.repo.note_handler_finished(job.id, job.attempt_seq)
                    await self.repo.finish(job.id, token, execution.result())
                    return
                valid, cancelled = await self.repo.heartbeat(job.id, token)
                if not valid or cancelled:
                    execution.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await execution
                    if valid:
                        await self.repo.finish(job.id, token, Outcome("cancelled"))
                    else:
                        log.warning(
                            "worker_lease_lost",
                            job_id=str(job.id),
                            worker_id=self.worker_id,
                            attempt=job.attempt_seq,
                            queue=job.queue,
                            task=job.task,
                        )
                    return
                log.info(
                    "lease_extended",
                    job_id=str(job.id),
                    worker_id=self.worker_id,
                    attempt=job.attempt_seq,
                    queue=job.queue,
                    task=job.task,
                )
        except asyncio.CancelledError:
            execution.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await execution
            # Grace expired: stop the handler before relinquishing durable ownership.
            await self.repo.finish(
                job.id, token, Outcome("failed", error="Worker shutdown grace expired")
            )
            raise
        finally:
            if not execution.done():
                execution.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await execution

    async def slot(self, slot_no: int) -> None:
        delay = 0.05
        queue_offset = slot_no
        while not self.stop.is_set():
            self.wakeups[slot_no].clear()
            try:
                found = False
                queues = self.runtime.settings.queue_names
                for index in range(len(queues)):
                    if self.stop.is_set():
                        break
                    queue = queues[(queue_offset + index) % len(queues)]
                    token = f"{self.worker_id}:{uuid4().hex}"
                    job_id = await self.runtime.broker.claim(queue, self.worker_id, token)
                    if job_id is None:
                        continue
                    found = True
                    log.info(
                        "job_claimed", job_id=str(job_id), worker_id=self.worker_id, queue=queue
                    )
                    job = await self.repo.begin_attempt(job_id, self.worker_id, token)
                    if job is None:
                        await self.runtime.broker.complete(queue, job_id, token)
                    else:
                        await self.execute(job, token)
                    break
                queue_offset += 1
                if found:
                    delay = 0.05
                    continue
                delay = min(1, delay * 2)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Infrastructure failures leave the durable attempt recoverable by its lease.
                log.error(
                    "worker_iteration_failed", worker_id=self.worker_id, error=type(exc).__name__
                )
                delay = min(5, max(0.1, delay * 2))
            try:
                await asyncio.wait_for(self.wakeups[slot_no].wait(), timeout=delay)
            except TimeoutError:
                pass

    async def notifications(self) -> None:
        """Best-effort wakeups reduce idle latency; periodic polls retain correctness."""
        delay = 0.1
        while not self.stop.is_set():
            try:
                async with self.runtime.redis.pubsub() as subscription:
                    await subscription.subscribe(
                        *[
                            self.runtime.broker.keys(queue)[0] + ":notify"
                            for queue in self.runtime.settings.queue_names
                        ]
                    )
                    while not self.stop.is_set():
                        message = await subscription.get_message(
                            ignore_subscribe_messages=True, timeout=1
                        )
                        if message is not None:
                            for wakeup in self.wakeups:
                                wakeup.set()
                        delay = 0.1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("notification_reconnecting", error=type(exc).__name__)
                await asyncio.sleep(delay)
                delay = min(5, delay * 2)

    async def registration_loop(self) -> None:
        while not self.stop.is_set():
            try:
                await self.repo.worker_heartbeat(self.worker_id)
            except Exception as exc:
                log.warning(
                    "worker_heartbeat_failed", worker_id=self.worker_id, error=type(exc).__name__
                )
            try:
                await asyncio.wait_for(self.stop.wait(), self.runtime.settings.heartbeat_ms / 1000)
            except TimeoutError:
                pass

    async def run(self) -> None:
        await self.repo.worker_heartbeat(self.worker_id)
        registration = asyncio.create_task(self.registration_loop())
        notifications = asyncio.create_task(self.notifications())
        slots = [
            asyncio.create_task(self.slot(i))
            for i in range(self.runtime.settings.worker_concurrency)
        ]
        try:
            await self.stop.wait()
            for wakeup in self.wakeups:
                wakeup.set()
            await registration
            await self.repo.worker_heartbeat(self.worker_id, "draining")
            _, pending = await asyncio.wait(slots, timeout=self.runtime.settings.shutdown_grace_s)
            for task in pending:
                task.cancel()
            await asyncio.gather(*slots, return_exceptions=True)
        finally:
            registration.cancel()
            notifications.cancel()
            for task in slots:
                task.cancel()
            await asyncio.gather(registration, notifications, *slots, return_exceptions=True)
            try:
                await self.repo.worker_heartbeat(self.worker_id, "stopped")
            except Exception as exc:
                log.warning("worker_stop_record_failed", error=type(exc).__name__)


async def serve() -> None:
    configure_logging()
    runtime = Runtime(Settings())
    worker = Worker(runtime)
    server, thread = start_http_server(runtime.settings.metrics_port)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: loop.call_soon_threadsafe(worker.stop.set))
    try:
        delay = 0.1
        while not worker.stop.is_set():
            try:
                await runtime.ready()
                await worker.run()
                break
            except Exception as exc:
                log.warning("worker_reconnecting", error=type(exc).__name__)
                await asyncio.sleep(delay)
                delay = min(5, delay * 2)
    finally:
        await runtime.close()
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(timeout=2)


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
