"""Initial durable queue schema, including execution fencing and effect ledger."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

status = pg.ENUM(
    "scheduled",
    "queued",
    "running",
    "succeeded",
    "failed_retrying",
    "dead",
    "cancelled",
    name="job_status",
    create_type=False,
)


def upgrade():
    status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "jobs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("queue", sa.Text(), nullable=False, server_default="default"),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("priority", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("status", status, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("timeout_s", sa.Integer(), nullable=False, server_default="60"),
        sa.Column(
            "run_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("idempotency_key", sa.Text()),
        sa.Column("result", pg.JSONB()),
        sa.Column("last_error", sa.Text()),
        sa.Column("locked_by", sa.Text()),
        sa.Column("claim_token", sa.String(200)),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("priority IN (0,1,2)"),
        sa.CheckConstraint("max_attempts BETWEEN 1 AND 20"),
        sa.CheckConstraint("timeout_s BETWEEN 1 AND 3600"),
        sa.CheckConstraint("attempts >= 0 AND attempt_seq >= attempts"),
    )
    op.create_index(
        "ux_jobs_idem",
        "jobs",
        ["queue", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_jobs_status_runat", "jobs", ["status", "run_at"])
    op.create_index("ix_jobs_created", "jobs", [sa.text("created_at DESC"), sa.text("id DESC")])
    op.create_table(
        "job_attempts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("outcome", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("handler_finished_at", sa.DateTime(timezone=True)),
        sa.Column("requeued_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("job_id", "attempt_no"),
        sa.CheckConstraint(
            "outcome IN ('succeeded','failed','timed_out','lease_expired','cancelled')"
        ),
    )
    op.create_table(
        "workers",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=False),
        sa.Column("jobs_done", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.Text(), nullable=False),
        sa.CheckConstraint("status IN ('active','draining','stopped')"),
    )
    op.create_table(
        "side_effects",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", pg.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade():
    for table in ("side_effects", "workers", "job_attempts", "jobs"):
        op.drop_table(table)
    status.drop(op.get_bind())
