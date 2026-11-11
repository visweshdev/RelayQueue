import hashlib
import json

import httpx
import pytest

from relayqueue.config import Settings
from relayqueue.examples import sales_report as example
from relayqueue.worker.runner import run_handler

SAMPLE = "sku,quantity,unit_price\nCOFFEE,2,12.50\nTEA,3,4.20\nCOFFEE,1,12.50\n"


async def test_sales_report_exact_totals_and_replay():
    first = await run_handler("sales_report", {"content": SAMPLE}, 5, Settings())
    second = await run_handler("sales_report", {"content": SAMPLE}, 5, Settings())
    assert first == second
    assert first.result == {
        "source_sha256": hashlib.sha256(SAMPLE.encode()).hexdigest(),
        "rows": 3,
        "units": 6,
        "revenue": "50.10",
        "products": [
            {"sku": "COFFEE", "units": 3, "revenue": "37.50"},
            {"sku": "TEA", "units": 3, "revenue": "12.60"},
        ],
    }


@pytest.mark.parametrize(
    "content",
    [
        "wrong,header\n1,2\n",
        "sku,quantity,unit_price\n",
        "sku,quantity,unit_price\nA,1\n",
        "sku,quantity,unit_price\nA,1,1.00,extra\n",
        'sku,quantity,unit_price\n"unclosed,1,1.00',
        *[f"sku,quantity,unit_price\nA,{value},1.00\n" for value in ("-1", "0", "1.5", "1000000")],
        *[
            f"sku,quantity,unit_price\nA,1,{value}\n"
            for value in ("NaN", "Infinity", "-1.00", "0.001", "1e2", "100000000.00")
        ],
        "sku,quantity,unit_price\n=FORMULA,1,1.00\n",
        "sku,quantity,unit_price\n" + "A,1,1.00\n" * 1001,
        "sku,quantity,unit_price\n" + "".join(f"A{i},1,1.00\n" for i in range(101)),
    ],
)
async def test_invalid_csv_is_failed_without_exposing_contents(content):
    outcome = await run_handler("sales_report", {"content": content}, 5, Settings())
    assert outcome.kind == "failed"
    assert outcome.result is None
    assert outcome.error.startswith("Handler failed:")


async def test_csv_boundary_bom_and_decimal_precision():
    content = "\ufeffsku,quantity,unit_price\n" + "A,1,0.10\n" * 1000
    result = await run_handler("sales_report", {"content": content}, 5, Settings())
    assert result.kind == "succeeded"
    assert result.result["rows"] == 1000
    assert result.result["revenue"] == "100.00"


async def test_demo_verifies_deduplication_and_failure_history(monkeypatch):
    submissions = []

    def respond(request):
        assert request.headers["X-API-Key"] == "test-key"
        if request.method == "POST":
            spec = json.loads(request.content)
            submissions.append(spec)
            return httpx.Response(
                201,
                json={"id": "bad" if spec["payload"]["content"].startswith("wrong") else "good"},
            )
        bad = request.url.path.endswith("bad")
        return httpx.Response(
            200,
            json={
                "status": "dead" if bad else "succeeded",
                "attempts": 2 if bad else 1,
                "result": {"revenue": "50.10"},
                "history": [{"outcome": "failed"}] * 2 if bad else [],
            },
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        example.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    result = await example.run(SAMPLE, "http://test", "test-key", True)
    assert result["revenue"] == "50.10"
    assert submissions[0]["idempotency_key"] == submissions[1]["idempotency_key"]
