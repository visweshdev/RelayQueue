"""Generate secrets for the isolated local HTTPS rehearsal; never overwrite existing files."""

import hashlib
import json
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1] / ".secrets"
root.mkdir(mode=0o700, exist_ok=True)
names = [
    "postgres_password",
    "redis_password",
    "database_url",
    "redis_url",
    "auth_policy.json",
    "alpha.key",
    "beta.key",
]
if any((root / name).exists() for name in names):
    raise SystemExit("Existing secrets found; refusing partial rotation. Use the rotation runbook.")
database, redis = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
tokens = {queue: secrets.token_urlsafe(32) for queue in ("alpha", "beta")}
values = {
    "postgres_password": database,
    "redis_password": redis,
    "database_url": f"postgresql+asyncpg://relayqueue:{database}@postgres:5432/relayqueue",
    "redis_url": f"redis://:{redis}@redis:6379/0",
    "auth_policy.json": json.dumps(
        {hashlib.sha256(token.encode()).hexdigest(): queue for queue, token in tokens.items()}
    ),
    **{f"{queue}.key": token for queue, token in tokens.items()},
}
for name, value in values.items():
    path = root / name
    with path.open("x", encoding="utf-8") as handle:
        handle.write(value)
    path.chmod(0o600)
print("Created private .secrets files for alpha and beta. Tokens were not printed.")
