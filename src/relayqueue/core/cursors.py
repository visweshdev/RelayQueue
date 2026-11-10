import base64
import json
from datetime import datetime
from uuid import UUID


def encode_cursor(created_at: datetime, job_id: UUID) -> str:
    return base64.urlsafe_b64encode(
        json.dumps([created_at.isoformat(), str(job_id)]).encode()
    ).decode()


def decode_cursor(value: str) -> tuple[datetime, UUID]:
    try:
        if len(value) > 256:
            raise ValueError("Cursor too long")
        timestamp, identifier = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
        parsed = datetime.fromisoformat(timestamp)
        if parsed.tzinfo is None:
            raise ValueError("Cursor timestamp needs timezone")
        return parsed, UUID(identifier)
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("Invalid pagination cursor") from exc
