"""Bounded demonstration handlers. Payloads are never logged."""

import asyncio
import os
import random
import sys
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from relayqueue.worker.handlers.sales_report import SalesInput, sales_report
from relayqueue.worker.registry import Context, registry


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoopInput(Payload):
    pass


class SleepInput(Payload):
    seconds: float = Field(ge=0, le=3600, allow_inf_nan=False)


class FlakyInput(Payload):
    fail_rate: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)


class HashInput(Payload):
    buffer: str = Field(default="relayqueue", max_length=32768)
    iterations: int = Field(default=10_000, ge=1, le=1_000_000_000)


class HttpInput(Payload):
    url: HttpUrl
    timeout_s: float = Field(default=5, gt=0, le=30, allow_inf_nan=False)


class OkResult(BaseModel):
    ok: bool = True


class SleepResult(BaseModel):
    slept: float


class HashResult(BaseModel):
    digest: str
    iterations: int


class HttpResult(BaseModel):
    status_code: int
    bytes_received: int


async def noop(payload: NoopInput, context: Context) -> BaseModel:
    return OkResult()


async def sleep(payload: SleepInput, context: Context) -> BaseModel:
    await asyncio.sleep(payload.seconds)
    return SleepResult(slept=payload.seconds)


async def flaky(payload: FlakyInput, context: Context) -> BaseModel:
    if random.random() < payload.fail_rate:
        raise RuntimeError("Configured flaky failure")
    return OkResult()


async def cpu_hash(payload: HashInput, context: Context) -> BaseModel:
    # A process can be killed and joined; cancelling a thread cannot stop CPU work.
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "relayqueue.worker.hash_process",
        str(os.getpid()),
        str(context.timeout_s),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await process.communicate(payload.model_dump_json().encode())
        if process.returncode:
            raise RuntimeError("Hash subprocess exited without a result")
        return HashResult.model_validate_json(output)
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()


def allowed_origin(url: str, allowed: str) -> bool:
    target = urlsplit(url)
    if target.username or target.password or target.scheme not in {"http", "https"}:
        return False
    origin = f"{target.scheme}://{target.netloc}".lower()
    return origin in {
        item.strip().rstrip("/").lower() for item in allowed.split(",") if item.strip()
    }


async def http_call(payload: HttpInput, context: Context) -> BaseModel:
    if not allowed_origin(str(payload.url), context.settings.http_allowed_origins):
        raise ValueError("HTTP destination is not in HTTP_ALLOWED_ORIGINS")
    # Explicit trusted origins only; no proxy env or redirect to another destination.
    async with httpx.AsyncClient(
        timeout=payload.timeout_s, trust_env=False, follow_redirects=False
    ) as client:
        async with client.stream("GET", str(payload.url)) as response:
            response.raise_for_status()
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > context.settings.max_payload_bytes:
                    raise ValueError("HTTP response exceeds configured size limit")
            return HttpResult(status_code=response.status_code, bytes_received=size)


registry.register("noop", NoopInput, noop)
registry.register("sleep", SleepInput, sleep)
registry.register("flaky", FlakyInput, flaky)
registry.register("cpu_hash", HashInput, cpu_hash)
registry.register("http_call", HttpInput, http_call)
registry.register("sales_report", SalesInput, sales_report)
