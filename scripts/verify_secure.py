"""Verify local TLS, tenant isolation, and a real CSV result without printing keys."""

import ssl
import time
from pathlib import Path
from uuid import uuid4

import httpx

root = Path(__file__).resolve().parents[1]
context = ssl.create_default_context(cafile=str(root / ".secrets/local-ca.crt"))
alpha = {"X-API-Key": (root / ".secrets/alpha.key").read_text().strip()}
beta = {"X-API-Key": (root / ".secrets/beta.key").read_text().strip()}
with httpx.Client(base_url="https://localhost:8443", verify=context, timeout=15) as client:
    assert client.get("/ui/index.html").status_code == 200
    assert client.get("/ui/style.css").status_code == 200
    for path in ("/metrics", "/ready", "/docs", "/openapi.json"):
        assert client.get(path).status_code == 404
    assert client.get("/v1/jobs").status_code == 401
    assert client.get("/v1/jobs", headers={"X-API-Key": "dev-key-1"}).status_code == 401
    assert client.get("/v1/session", headers=alpha).json() == {"queue": "alpha"}
    spec = {
        "task": "sales_report",
        "queue": "alpha",
        "idempotency_key": str(uuid4()),
        "payload": {"content": (root / "examples/sales.csv").read_text()},
    }
    response = client.post("/v1/jobs", headers=alpha, json=spec)
    assert response.status_code == 201, response.status_code
    identifier = response.json()["id"]
    assert client.get(f"/v1/jobs/{identifier}", headers=beta).status_code == 404
    for action in ("cancel", "retry"):
        assert client.post(f"/v1/jobs/{identifier}/{action}", headers=beta).status_code == 404
    assert client.post("/v1/jobs", headers=beta, json=spec).status_code == 404
    assert client.get("/v1/workers", headers=beta).status_code == 403
    for _ in range(60):
        job = client.get(f"/v1/jobs/{identifier}", headers=alpha).json()
        if job["status"] == "succeeded":
            break
        time.sleep(1)
    else:
        raise RuntimeError("CSV job did not complete")
    assert "50.10" in str(job["result"])
    assert all(
        item["queue"] == "beta" for item in client.get("/v1/jobs", headers=beta).json()["items"]
    )
print("PASS: trusted TLS, protected routes, tenant boundaries, CSV result 50.10")
