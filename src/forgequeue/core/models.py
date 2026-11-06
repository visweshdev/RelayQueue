from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from forgequeue.core.states import Status


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("priority IN (0,1,2)"),
        CheckConstraint("max_attempts BETWEEN 1 AND 20"),
        CheckConstraint("timeout_s BETWEEN 1 AND 3600"),
        CheckConstraint("attempts >= 0 AND attempt_seq >= attempts"),
        Index(
            "ux_jobs_idem",
            "queue",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_jobs_status_runat", "status", "run_at"),
        Index("ix_jobs_created", text("created_at DESC"), text("id DESC")),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    queue: Mapped[str] = mapped_column(Text, default="default")
    task: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    priority: Mapped[int] = mapped_column(SmallInteger, default=1)
    status: Mapped[Status] = mapped_column(
        Enum(Status, name="job_status", values_callable=lambda e: [s.value for s in e])
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    attempt_seq: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    timeout_s: Mapped[int] = mapped_column(Integer, default=60)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    last_error: Mapped[str | None] = mapped_column(Text)
    locked_by: Mapped[str | None] = mapped_column(Text)
    claim_token: Mapped[str | None] = mapped_column(String(200))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Attempt(Base):
    __tablename__ = "job_attempts"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt_no"),
        CheckConstraint(
            "outcome IN ('succeeded','failed','timed_out','lease_expired','cancelled')"
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    attempt_no: Mapped[int] = mapped_column(Integer)
    worker_id: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    handler_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requeued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkerRecord(Base):
    __tablename__ = "workers"
    __table_args__ = (CheckConstraint("status IN ('active','draining','stopped')"),)
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_heartbeat: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    jobs_done: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(Text, default="active")


class SideEffect(Base):
    __tablename__ = "side_effects"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
