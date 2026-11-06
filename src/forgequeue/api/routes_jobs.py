import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from forgequeue.api.auth import authenticate
from forgequeue.api.deps import get_repo, get_runtime
from forgequeue.api.ratelimit import submission_limit
from forgequeue.api.schemas import (
    AttemptResponse,
    JobCreate,
    JobDetails,
    JobPage,
    JobResponse,
)
from forgequeue.core.repo import Repository
from forgequeue.core.states import Status

router = APIRouter(prefix="/v1/jobs", dependencies=[Depends(authenticate)])
Repo = Annotated[Repository, Depends(get_repo)]


@router.post(
    "", response_model=JobResponse, status_code=201, dependencies=[Depends(submission_limit)]
)
async def submit(spec: JobCreate, response: Response, request: Request, repo: Repo) -> JobResponse:
    settings = get_runtime(request).settings
    if spec.queue not in settings.queue_names:
        raise HTTPException(400, "Queue is not configured in QUEUES")
    if len(json.dumps(spec.payload, ensure_ascii=False).encode()) > settings.max_payload_bytes:
        raise HTTPException(413, "Payload exceeds configured size limit")
    job, created = await repo.submit(spec)
    response.status_code = 201 if created else 200
    return JobResponse.model_validate(job)


@router.get("", response_model=JobPage)
async def list_jobs(
    repo: Repo,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
    status: Status | None = None,
    queue: str | None = None,
    task: str | None = None,
) -> JobPage:
    try:
        jobs, next_cursor = await repo.list_jobs(
            limit=limit, cursor=cursor, status=status, queue=queue, task=task
        )
    except ValueError as exc:
        raise HTTPException(400, "Invalid pagination cursor") from exc
    return JobPage(items=[JobResponse.model_validate(job) for job in jobs], next_cursor=next_cursor)


@router.get("/{job_id}", response_model=JobDetails)
async def get_job(job_id: UUID, repo: Repo) -> JobDetails:
    job, history = await repo.get(job_id)
    return JobDetails(
        **JobResponse.model_validate(job).model_dump(),
        history=[AttemptResponse.model_validate(attempt) for attempt in history],
    )


@router.post("/{job_id}/cancel", response_model=JobResponse, status_code=202)
async def cancel_job(job_id: UUID, repo: Repo) -> JobResponse:
    return JobResponse.model_validate(await repo.cancel(job_id))


@router.post("/{job_id}/retry", response_model=JobResponse, status_code=202)
async def retry_job(job_id: UUID, repo: Repo) -> JobResponse:
    return JobResponse.model_validate(await repo.retry(job_id))
