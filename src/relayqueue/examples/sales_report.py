"""Submit a CSV file and follow durable job state; requires a running RelayQueue API."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx


async def submit(client: httpx.AsyncClient, content: str, key: str) -> dict[str, Any]:
    response = await client.post(
        "/v1/jobs",
        json={
            "task": "sales_report",
            "payload": {"content": content},
            "idempotency_key": key,
            "max_attempts": 2,
        },
    )
    response.raise_for_status()
    return dict(response.json())


async def follow(client: httpx.AsyncClient, identifier: str) -> dict[str, Any]:
    previous = None
    async with asyncio.timeout(120):
        while True:
            response = await client.get(f"/v1/jobs/{identifier}")
            response.raise_for_status()
            job = dict(response.json())
            state = (job["status"], job["attempts"])
            if state != previous:
                print(f"{identifier}: {state[0]} (attempts: {state[1]})", flush=True)
                previous = state
            if job["status"] in {"succeeded", "dead", "cancelled"}:
                return job
            await asyncio.sleep(0.25)


async def run(content: str, url: str, key: str, verify_demo: bool) -> dict[str, Any]:
    async with httpx.AsyncClient(
        base_url=url, headers={"X-API-Key": key}, timeout=15, trust_env=False
    ) as client:
        digest = hashlib.sha256(content.encode()).hexdigest()
        job = await submit(client, content, f"sales-report:v1:{digest}")
        result = await follow(client, job["id"])
        if result["status"] != "succeeded":
            raise RuntimeError(f"Report ended in {result['status']}; inspect job attempt history")
        print(json.dumps(result["result"], indent=2), flush=True)
        if verify_demo:
            repeated = await submit(client, content, f"sales-report:v1:{digest}")
            if repeated["id"] != job["id"]:
                raise RuntimeError("Duplicate submission created another job")
            print("PASS: identical file submission returns the same job", flush=True)
            invalid = await submit(client, "wrong,header\n1,2\n", f"sales-demo:invalid:{uuid4()}")
            failed = await follow(client, invalid["id"])
            if failed["status"] != "dead" or len(failed["history"]) != 2:
                raise RuntimeError("Invalid file did not exhaust exactly two attempts")
            if any(attempt["outcome"] != "failed" for attempt in failed["history"]):
                raise RuntimeError("Unexpected failure history")
            print("PASS: invalid CSV retried twice and reached the dead-letter queue", flush=True)
        return dict(result["result"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--url", default=os.getenv("RELAYQUEUE_URL", "http://localhost:8000"))
    parser.add_argument("--verify-demo", action="store_true")
    parser.add_argument("--output", type=Path, help="Write the report JSON to this local file")
    args = parser.parse_args()
    raw = args.file.read_bytes()
    if len(raw) > 48_000:
        parser.error("CSV must be at most 48000 bytes")
    try:
        content = raw.decode("utf-8-sig")
        report = asyncio.run(
            run(content, args.url, os.getenv("API_KEY", "dev-key-1"), args.verify_demo)
        )
        if args.output:
            args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except (UnicodeError, httpx.HTTPError, TimeoutError, RuntimeError) as exc:
        parser.exit(1, f"Report failed: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()
