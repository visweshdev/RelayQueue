"""Check actual Prometheus targets and the provisioned Grafana dashboard."""

import asyncio
import os

import httpx

from bench.common import save_result


async def main():
    async with httpx.AsyncClient(timeout=10) as client:
        async with asyncio.timeout(90):
            while True:
                response = await client.get("http://localhost:9090/api/v1/targets")
                response.raise_for_status()
                targets = response.json()["data"]["activeTargets"]
                workers = [t for t in targets if t["labels"].get("job") == "workers"]
                if len(workers) >= 4 and all(t["health"] == "up" for t in targets):
                    break
                await asyncio.sleep(2)
        dashboard = await client.get(
            "http://localhost:3000/api/dashboards/uid/relayqueue",
            auth=("admin", os.getenv("GRAFANA_PASSWORD", "forgequeue-local")),
        )
        dashboard.raise_for_status()
        assert len(dashboard.json()["dashboard"]["panels"]) >= 8
        save_result(
            "monitoring.json",
            {
                "healthy_targets": len(targets),
                "worker_targets": len(workers),
                "dashboard_uid": "relayqueue",
                "verified": True,
            },
        )


if __name__ == "__main__":
    asyncio.run(main())
