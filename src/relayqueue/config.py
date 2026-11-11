import json
import re
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://fq:fq@postgres:5432/fq"
    redis_url: str = "redis://redis:6379/0"
    api_keys: str = "dev-key-1"
    auth_policy_file: str | None = None
    tenant_keys: dict[str, str] = Field(default_factory=dict)
    database_url_file: str | None = None
    redis_url_file: str | None = None
    secure_mode: bool = False
    queues: str = "default"
    lease_ms: int = Field(default=30_000, ge=300)
    heartbeat_ms: int = Field(default=10_000, ge=100)
    reaper_interval_ms: int = Field(default=5_000, ge=100)
    scheduler_interval_ms: int = Field(default=1_000, ge=100)
    reconcile_interval_s: float = Field(default=60, gt=0, allow_inf_nan=False)
    base_backoff_s: float = Field(default=2, ge=0, allow_inf_nan=False)
    max_backoff_s: float = Field(default=300, ge=0, allow_inf_nan=False)
    worker_concurrency: int = Field(default=1, ge=1, le=64)
    shutdown_grace_s: float = Field(default=30, gt=0, allow_inf_nan=False)
    max_payload_bytes: int = Field(default=65_536, ge=1, le=65_536)
    rate_limit_per_s: int = Field(default=200, ge=1)
    metrics_port: int = Field(default=9100, ge=1, le=65535)
    http_allowed_origins: str = ""
    db_pool_size: int = Field(default=10, ge=1)
    batch_size: int = Field(default=200, ge=1, le=1000)

    @model_validator(mode="after")
    def validate_timing(self) -> "Settings":
        for name in ("database_url", "redis_url"):
            path = getattr(self, f"{name}_file")
            if path:
                setattr(self, name, Path(path).read_text(encoding="utf-8").strip())
        if self.auth_policy_file:
            self.tenant_keys = json.loads(Path(self.auth_policy_file).read_text(encoding="utf-8"))
        if not isinstance(self.tenant_keys, dict) or any(
            not isinstance(digest, str)
            or re.fullmatch(r"[a-f0-9]{64}", digest) is None
            or queue not in self.queue_names
            for digest, queue in self.tenant_keys.items()
        ):
            raise ValueError("Auth policy must map SHA-256 token digests to configured queues")
        if self.secure_mode and not (
            self.tenant_keys and self.database_url_file and self.redis_url_file
        ):
            raise ValueError("Secure mode requires tenant policy and file-mounted database secrets")
        if self.heartbeat_ms * 3 > self.lease_ms:
            raise ValueError("HEARTBEAT_MS must be at most LEASE_MS / 3")
        if self.max_backoff_s < self.base_backoff_s:
            raise ValueError("MAX_BACKOFF_S must be >= BASE_BACKOFF_S")
        if not self.key_set or not self.queue_names:
            raise ValueError("API_KEYS and QUEUES must not be empty")
        if any(re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", q) is None for q in self.queue_names):
            raise ValueError("QUEUES must contain valid queue names")
        return self

    @property
    def key_set(self) -> set[str]:
        return {key.strip() for key in self.api_keys.split(",") if key.strip()}

    @property
    def queue_names(self) -> tuple[str, ...]:
        return tuple(q.strip() for q in self.queues.split(",") if q.strip())
