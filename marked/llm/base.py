from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLM(Protocol):
    name: str
    available: bool

    def complete_structured(self, system: str, user: str, output: type[T], max_tokens: int = 4000) -> T | None: ...


class NullLLM:
    name = "none"
    available = False

    def complete_structured(self, system: str, user: str, output: type[T], max_tokens: int = 4000) -> T | None:
        return None
