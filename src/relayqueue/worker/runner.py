import asyncio
import json
from dataclasses import dataclass
from typing import Any

from relayqueue.config import Settings
from relayqueue.worker import handlers  # noqa: F401 - registers built-ins
from relayqueue.worker.registry import Context, registry


@dataclass(frozen=True)
class Outcome:
    kind: str
    result: dict[str, Any] | None = None
    error: str | None = None


async def run_handler(
    task: str, payload: dict[str, Any], timeout_s: int, settings: Settings
) -> Outcome:
    try:
        async with asyncio.timeout(timeout_s):
            result = await registry.get(task).run(payload, Context(settings, timeout_s))
            if (
                len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode())
                > settings.max_payload_bytes
            ):
                raise ValueError("Result exceeds configured size limit")
            return Outcome("succeeded", result=result)
    except TimeoutError:
        return Outcome("timed_out", error="Execution timeout exceeded")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # Do not persist URLs, credentials, payloads, or arbitrary exception messages.
        return Outcome("failed", error=f"Handler failed: {type(exc).__name__}")
