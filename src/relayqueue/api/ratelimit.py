from typing import Annotated

from fastapi import Depends, HTTPException, Request

from relayqueue.api.auth import authenticate
from relayqueue.api.deps import get_runtime


async def submission_limit(request: Request, key: Annotated[str, Depends(authenticate)]) -> None:
    runtime = get_runtime(request)
    if not await runtime.broker.rate_limit(key, runtime.settings.rate_limit_per_s):
        raise HTTPException(429, "Submission rate exceeded", headers={"Retry-After": "1"})
