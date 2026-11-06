from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel

from forgequeue.config import Settings

Input = TypeVar("Input", bound=BaseModel)


@dataclass(frozen=True)
class Context:
    settings: Settings
    timeout_s: int


@dataclass(frozen=True)
class Handler:
    schema: type[BaseModel]
    run: Callable[[dict[str, Any], Context], Awaitable[dict[str, Any]]]


class Registry:
    def __init__(self) -> None:
        self.handlers: dict[str, Handler] = {}

    def register(
        self,
        name: str,
        schema: type[Input],
        execute: Callable[[Input, Context], Awaitable[BaseModel]],
    ) -> None:
        if name in self.handlers:
            raise ValueError(f"Handler already registered: {name}")

        async def run(payload: dict[str, Any], context: Context) -> dict[str, Any]:
            return (await execute(schema.model_validate(payload), context)).model_dump(mode="json")

        self.handlers[name] = Handler(schema, run)

    def get(self, name: str) -> Handler:
        try:
            return self.handlers[name]
        except KeyError as exc:
            raise ValueError(f"Unknown task: {name}") from exc


registry = Registry()
