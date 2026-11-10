import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from relayqueue.api import routes_admin, routes_jobs
from relayqueue.api.schemas import ErrorResponse
from relayqueue.config import Settings
from relayqueue.core.repo import Conflict, NotFound
from relayqueue.obs.logging import configure_logging
from relayqueue.obs.metrics import HTTP
from relayqueue.runtime import Runtime

log = structlog.get_logger()


def error(
    status: int, code: str, message: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        ErrorResponse(code=code, message=message).model_dump(), status_code=status, headers=headers
    )


class BodyLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        chunks: list[bytes] = []
        size = 0
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            data = event.get("body", b"")
            size += len(data)
            if size > 512 * 1024:
                await error(413, "payload_too_large", "Request body too large")(
                    scope, receive, send
                )
                return
            chunks.append(data)
            if not event.get("more_body", False):
                break
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def create_app(runtime: Runtime | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        app.state.runtime = runtime or Runtime(Settings())
        yield
        if runtime is None:
            await app.state.runtime.close()

    app = FastAPI(title="RelayQueue", version="0.1.0", lifespan=lifespan)
    if runtime is not None:
        app.state.runtime = runtime
    app.add_middleware(BodyLimit)
    app.include_router(routes_jobs.router)
    app.include_router(routes_admin.router)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return error(exc.status_code, f"http_{exc.status_code}", str(exc.detail), exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        oversized = any(e["type"] == "payload_size" for e in exc.errors())
        status = 413 if oversized else 422
        if request.method == "GET" and request.url.path == "/v1/jobs":
            status = 400
        return error(
            status, "invalid_request", "Payload too large" if oversized else "Invalid request"
        )

    @app.exception_handler(NotFound)
    async def not_found(request: Request, exc: NotFound) -> JSONResponse:
        return error(404, "not_found", "Job not found")

    @app.exception_handler(Conflict)
    async def conflict(request: Request, exc: Conflict) -> JSONResponse:
        return error(409, "conflict", str(exc))

    async def unavailable(request: Request, exc: Exception) -> JSONResponse:
        log.error("dependency_unavailable", error=type(exc).__name__)
        return error(503, "unavailable", "Service temporarily unavailable")

    app.add_exception_handler(RedisError, unavailable)
    app.add_exception_handler(SQLAlchemyError, unavailable)
    app.add_exception_handler(OSError, unavailable)

    @app.middleware("http")
    async def observe(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.monotonic()
        response = await call_next(request)
        route = getattr(request.scope.get("route"), "path", "unmatched")
        HTTP.labels(route, request.method, response.status_code).observe(time.monotonic() - started)
        return response

    return app


app = create_app()
