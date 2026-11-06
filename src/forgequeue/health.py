import asyncio
import socket

from forgequeue.config import Settings
from forgequeue.core.repo import Repository
from forgequeue.runtime import Runtime


async def check() -> None:
    runtime = Runtime(Settings())
    try:
        await runtime.ready()
        workers = await Repository(runtime).worker_stats()
        if not any(w["id"].startswith(socket.gethostname() + ":") and w["alive"] for w in workers):
            raise RuntimeError("No live worker on this host")
    finally:
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(check())
