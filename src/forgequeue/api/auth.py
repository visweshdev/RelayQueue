import secrets
from typing import Annotated

from fastapi import Header, HTTPException, Request

from forgequeue.api.deps import get_runtime


async def authenticate(request: Request, x_api_key: Annotated[str | None, Header()] = None) -> str:
    keys = get_runtime(request).settings.key_set
    if x_api_key is None or not any(
        secrets.compare_digest(x_api_key.encode(), key.encode()) for key in keys
    ):
        raise HTTPException(401, "Invalid API key")
    return x_api_key
