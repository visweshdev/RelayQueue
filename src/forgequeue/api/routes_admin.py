import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest, multiprocess

from forgequeue.api.auth import authenticate
from forgequeue.api.deps import get_repo, get_runtime
from forgequeue.api.schemas import Health, QueueStat, WorkerResponse
from forgequeue.core.repo import Repository

router = APIRouter()
Repo = Annotated[Repository, Depends(get_repo)]


@router.get("/health", response_model=Health)
async def health() -> Health:
    return Health(status="ok")


@router.get("/ready", response_model=Health)
async def ready(request: Request) -> Health:
    try:
        await get_runtime(request).ready()
    except Exception as exc:
        raise HTTPException(503, "Dependencies unavailable") from exc
    return Health(status="ready")


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    if os.getenv("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        # prometheus-client does not annotate this collector's constructor.
        multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
        content = generate_latest(registry)
    else:
        content = generate_latest()
    return Response(content, headers={"Content-Type": CONTENT_TYPE_LATEST})


@router.get(
    "/v1/queues/stats", response_model=list[QueueStat], dependencies=[Depends(authenticate)]
)
async def queue_stats(repo: Repo) -> list[QueueStat]:
    return [QueueStat.model_validate(row) for row in await repo.queue_stats()]


@router.get(
    "/v1/workers", response_model=list[WorkerResponse], dependencies=[Depends(authenticate)]
)
async def workers(repo: Repo) -> list[WorkerResponse]:
    return [WorkerResponse.model_validate(row) for row in await repo.worker_stats()]
