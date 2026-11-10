from typing import cast

from fastapi import Request

from relayqueue.core.repo import Repository
from relayqueue.runtime import Runtime


def get_runtime(request: Request) -> Runtime:
    return cast(Runtime, request.app.state.runtime)


async def get_repo(request: Request) -> Repository:
    return Repository(get_runtime(request))
