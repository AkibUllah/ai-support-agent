"""Provider-neutral message format.

Messages are stored and replayed in this shape::

    {"role": "user", "content": "..."}
    {"role": "assistant", "content": "...", "tool_calls": [{"id", "name", "arguments"}]}
    {"role": "tool", "tool_call_id": "...", "name": "...", "content": "<json>"}

Adapters translate to each provider's wire format and back.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(RuntimeError):
    """The provider failed or returned something unusable."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "arguments": self.arguments}


@dataclass(frozen=True)
class AssistantMessage:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLM(Protocol):
    name: str

    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AssistantMessage: ...


class ScriptedLLM:
    """Replays canned assistant messages (or calls a function) — for unit tests."""

    name = "scripted"

    def __init__(
        self,
        script: Iterable[AssistantMessage] | Callable[[list[dict[str, Any]]], AssistantMessage],
    ) -> None:
        self._fn = script if callable(script) else None
        self._queue = [] if callable(script) else list(script)
        self.calls: list[list[dict[str, Any]]] = []

    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AssistantMessage:
        self.calls.append(list(messages))
        if self._fn is not None:
            return self._fn(messages)
        if not self._queue:
            raise LLMError("ScriptedLLM ran out of messages")
        return self._queue.pop(0)
