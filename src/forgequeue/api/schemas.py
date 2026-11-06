import json
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from forgequeue.core.states import Status
from forgequeue.worker import handlers  # noqa: F401
from forgequeue.worker.registry import registry


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    queue: str = Field(default="default", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    priority: int = Field(default=1, ge=0, le=2)
    max_attempts: int = Field(default=5, ge=1, le=20)
    timeout_s: int = Field(default=60, ge=1, le=3600)
    run_at: AwareDatetime | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_job(self) -> "JobCreate":
        if len(json.dumps(self.payload, ensure_ascii=False, allow_nan=False).encode()) > 65_536:
            raise PydanticCustomError("payload_size", "Payload exceeds 65536 bytes")
        registry.get(self.task).schema.model_validate(self.payload)
        return self


class ErrorResponse(BaseModel):
    code: str
    message: str


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    queue: str
    task: str
    payload: dict[str, Any]
    priority: int
    status: Status
    attempts: int
    attempt_seq: int
    max_attempts: int
    timeout_s: int
    run_at: datetime
    idempotency_key: str | None
    result: dict[str, Any] | None
    last_error: str | None
    locked_by: str | None
    cancel_requested: bool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class AttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    attempt_no: int
    worker_id: str
    started_at: datetime
    finished_at: datetime | None
    outcome: str | None
    error: str | None
    duration_ms: int | None
    handler_finished_at: datetime | None
    requeued_at: datetime | None


class JobDetails(JobResponse):
    history: list[AttemptResponse]


class JobPage(BaseModel):
    items: list[JobResponse]
    next_cursor: str | None


class WorkerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    started_at: datetime
    last_heartbeat: datetime
    jobs_done: int
    status: str
    alive: bool = False


class QueueStat(BaseModel):
    queue: str
    status: Status
    priority: int
    count: int
    oldest_ready_age_s: float | None = None


class Health(BaseModel):
    status: str
