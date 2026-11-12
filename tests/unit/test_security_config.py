import hashlib
import json

import pytest
from pydantic import ValidationError

from relayqueue.config import Settings


def test_secret_files_and_tenant_policy(tmp_path):
    database, redis, policy = (tmp_path / name for name in ("db", "redis", "policy"))
    database.write_text("postgresql+asyncpg://user:password@db/app")
    redis.write_text("redis://:password@redis:6379/0")
    mapping = {hashlib.sha256(b"token").hexdigest(): "default"}
    policy.write_text(json.dumps(mapping))
    settings = Settings(
        secure_mode=True,
        database_url_file=str(database),
        redis_url_file=str(redis),
        auth_policy_file=str(policy),
    )
    assert settings.tenant_keys == mapping
    assert settings.database_url == database.read_text()
    assert settings.redis_url == redis.read_text()


@pytest.mark.parametrize(
    "values",
    [
        {"secure_mode": True},
        {"tenant_keys": {"plaintext": "default"}},
        {"tenant_keys": {"a" * 64: "unknown"}},
    ],
)
def test_unsafe_policies_fail_closed(values):
    with pytest.raises(ValidationError):
        Settings(**values)
