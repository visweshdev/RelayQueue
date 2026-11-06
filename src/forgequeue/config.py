import re

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://fq:fq@postgres:5432/fq"
    redis_url: str = "redis://redis:6379/0"
    api_keys: str = "dev-key-1"
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
