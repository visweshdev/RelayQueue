import asyncio
import json
import os
import platform
import subprocess
import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import httpx
import psutil

ROOT = Path(__file__).resolve().parents[1]


def machine():
    if metadata := os.getenv("BENCH_HOST_METADATA"):
        return {
            **json.loads(metadata),
            "load_generator": {
                "os": platform.platform(),
                "python": platform.python_version(),
                "api_url": os.getenv("BENCH_API_URL"),
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }
    allocation = None
    image_id = None
    try:
        docker = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        resources = subprocess.run(
            ["docker", "info", "--format", "{{.NCPU}} {{.MemTotal}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if resources.returncode == 0:
            cpus, memory = resources.stdout.split()
            allocation = {"logical_cpus": int(cpus), "ram_bytes": int(memory)}
        image_id = subprocess.run(
            ["docker", "image", "inspect", "forgequeue:local", "--format", "{{.Id}}"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        docker = "unavailable"
    return {
        "cpu": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "ram_bytes": psutil.virtual_memory().total,
        "os": platform.platform(),
        "python": platform.python_version(),
        "docker_server": docker,
        "docker_allocation": allocation,
        "runtime_image_id": image_id,
        "source_sha256": sha256(
            b"".join(
                path.relative_to(ROOT).as_posix().encode() + path.read_bytes()
                for path in sorted((ROOT / "src").rglob("*"))
                if path.suffix in {".py", ".lua"}
            )
        ).hexdigest(),
        "timestamp": datetime.now(UTC).isoformat(),
    }


def percentile(values, percent):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * percent / 100))]


def save_result(name, result):
    target = ROOT / "bench" / "results" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return target


def run_in_container(module, arguments):
    results = ROOT / "bench/results"
    results.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            os.getenv("BENCH_DOCKER_NETWORK", "forgequeue_default"),
            "--mount",
            f"type=bind,source={results},target=/app/bench/results",
            "--env",
            "BENCH_API_URL=http://api:8000",
            "--env",
            f"API_KEY={os.getenv('API_KEY', 'dev-key-1')}",
            "--env",
            f"BENCH_HOST_METADATA={json.dumps(machine())}",
            "forgequeue-bench:local",
            "python",
            "-u",
            "-m",
            module,
            *arguments,
        ],
        cwd=ROOT,
        check=True,
        timeout=3600,
    )


def client(url=None):
    return httpx.AsyncClient(
        base_url=url or os.getenv("BENCH_API_URL", "http://localhost:8000"),
        timeout=15,
        headers={"X-API-Key": os.getenv("API_KEY", "dev-key-1")},
        limits=httpx.Limits(max_connections=64, max_keepalive_connections=32),
    )


async def wait_idle(api, deadline_s=900):
    async with asyncio.timeout(deadline_s):
        while True:
            response = await api.get("/v1/queues/stats")
            response.raise_for_status()
            pending = sum(
                row["count"]
                for row in response.json()
                if row["status"] in {"queued", "running", "failed_retrying", "scheduled"}
            )
            if not pending:
                return
            print(f"Waiting for {pending} previous jobs to drain", flush=True)
            await asyncio.sleep(15)


async def submit_many(api, count, *, task="noop", payload=None, concurrency=32):
    semaphore = asyncio.Semaphore(concurrency)
    latencies, retry_counts = [], []
    run_id = uuid4().hex

    async def submit(index):
        async with semaphore:
            started = time.perf_counter()
            body = {
                "task": task,
                "payload": payload or {},
                "idempotency_key": f"bench:{run_id}:{index}",
            }
            for retry in range(20):
                try:
                    response = await api.post("/v1/jobs", json=body)
                except httpx.TransportError:
                    await asyncio.sleep(min(0.1 * 2**retry, 2))
                    continue
                if response.status_code in {429, 503}:
                    await asyncio.sleep(min(0.1 * 2**retry, 2))
                    continue
                response.raise_for_status()
                latencies.append((time.perf_counter() - started) * 1000)
                retry_counts.append(retry)
                if count >= 1000 and len(latencies) % 1000 == 0:
                    print(f"Submitted {len(latencies)}/{count} jobs", flush=True)
                return response.json()["id"]
            raise RuntimeError("Submission did not recover within bounded retries")

    identifiers = await asyncio.gather(*[submit(i) for i in range(count)])
    return identifiers, latencies, sum(retry_counts)


async def snapshot(api, identifiers):
    wanted = set(identifiers)
    found, cursor = {}, None
    while True:
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        response = await api.get("/v1/jobs", params=params)
        response.raise_for_status()
        page = response.json()
        for job in page["items"]:
            if job["id"] in wanted:
                found[job["id"]] = job
        cursor = page["next_cursor"]
        if not cursor or len(found) == len(wanted):
            return found


async def wait_terminal(api, identifiers, deadline_s=900):
    deadline = time.monotonic() + deadline_s
    last_report = 0.0
    last = {}
    while time.monotonic() < deadline:
        try:
            last = await snapshot(api, identifiers)
            if len(last) == len(identifiers) and all(
                job["status"] in {"succeeded", "dead", "cancelled"} for job in last.values()
            ):
                return last
            if len(identifiers) >= 1000 and time.monotonic() - last_report >= 15:
                terminal = sum(
                    job["status"] in {"succeeded", "dead", "cancelled"} for job in last.values()
                )
                print(f"Drained {terminal}/{len(identifiers)} jobs", flush=True)
                last_report = time.monotonic()
        except (httpx.TransportError, httpx.HTTPStatusError):
            pass
        await asyncio.sleep(0.5)
    raise TimeoutError(f"Drain deadline exceeded: {len(last)}/{len(identifiers)} discoverable")


async def attempt_details(api, identifiers):
    semaphore = asyncio.Semaphore(16)

    async def get(identifier):
        async with semaphore:
            response = await api.get(f"/v1/jobs/{identifier}")
            response.raise_for_status()
            return response.json()

    return await asyncio.gather(*[get(identifier) for identifier in identifiers])
