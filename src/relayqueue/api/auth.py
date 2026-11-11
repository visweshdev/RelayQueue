import hashlib
import secrets
from typing import Annotated

from fastapi import Header, HTTPException, Request

from relayqueue.api.deps import get_runtime


async def authenticate(request: Request, x_api_key: Annotated[str | None, Header()] = None) -> str:
    settings = get_runtime(request).settings
    digest = hashlib.sha256((x_api_key or "").encode()).hexdigest()
    if settings.tenant_keys:
        for expected, queue in settings.tenant_keys.items():
            if x_api_key and secrets.compare_digest(digest, expected):
                request.state.allowed_queue = queue
                return digest
        raise HTTPException(401, "Invalid API key")
    keys = settings.key_set
    if x_api_key is None or not any(
        secrets.compare_digest(x_api_key.encode(), key.encode()) for key in keys
    ):
        raise HTTPException(401, "Invalid API key")
    request.state.allowed_queue = None
    return digest
