import asyncio
import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from relayqueue.config import Settings
from relayqueue.worker.handlers import NoopInput, allowed_origin, noop
from relayqueue.worker.registry import Registry
from relayqueue.worker.runner import run_handler


def test_registry_rejects_duplicates_and_unknowns():
    registry = Registry()
    registry.register("noop", NoopInput, noop)
    with pytest.raises(ValueError, match="already"):
        registry.register("noop", NoopInput, noop)
    with pytest.raises(ValueError, match="Unknown"):
        registry.get("missing")


@pytest.mark.parametrize(
    "task,payload,kind",
    [
        ("noop", {}, "succeeded"),
        ("sleep", {"seconds": 0.001}, "succeeded"),
        ("flaky", {"fail_rate": 0}, "succeeded"),
        ("flaky", {"fail_rate": 1}, "failed"),
        ("missing", {}, "failed"),
        ("sleep", {"seconds": 2}, "timed_out"),
    ],
)
async def test_handlers(task, payload, kind):
    outcome = await run_handler(task, payload, 1, Settings())
    assert outcome.kind == kind


async def test_cpu_hash_result():
    outcome = await run_handler("cpu_hash", {"buffer": "abc", "iterations": 2}, 5, Settings())
    expected = hashlib.sha256(hashlib.sha256(b"abc").digest()).hexdigest()
    assert outcome.kind == "succeeded"
    assert outcome.result == {"digest": expected, "iterations": 2}


async def test_cpu_timeout_stops_child():
    import psutil

    before = {p.pid for p in psutil.Process().children()}
    outcome = await run_handler("cpu_hash", {"iterations": 1_000_000_000}, 1, Settings())
    assert outcome.kind == "timed_out"
    assert {p.pid for p in psutil.Process().children()} <= before


async def test_cooperative_cancel_and_result_limit():
    task = asyncio.create_task(run_handler("sleep", {"seconds": 30}, 60, Settings()))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await run_handler("noop", {}, 5, Settings(max_payload_bytes=1))).kind == "failed"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://169.254.169.254/",
        "https://allowed.test.evil/",
        "http://u:p@allowed.test/",
        "file:///etc/passwd",
    ],
)
def test_http_allowlist_blocks_untrusted(url):
    assert not allowed_origin(url, "https://allowed.test")


async def test_http_requires_allowlist():
    result = await run_handler("http_call", {"url": "http://127.0.0.1/"}, 1, Settings())
    assert result.kind == "failed"


async def test_http_mock_service():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"hello")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        result = await run_handler(
            "http_call", {"url": origin}, 5, Settings(http_allowed_origins=origin)
        )
        assert result.result == {"status_code": 200, "bytes_received": 5}
        result = await run_handler(
            "http_call",
            {"url": origin},
            5,
            Settings(http_allowed_origins=origin, max_payload_bytes=4),
        )
        assert result.kind == "failed"
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(timeout=2)
