"""Tool plumbing: auth context, argument validation, error envelope, registry."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from support_agent.clock import Clock
from support_agent.domain.repository import Repository
from support_agent.faq import FAQIndex
from support_agent.policy import AddressPolicy, RefundPolicy


class ToolError(Exception):
    """A tool refused or failed; ``code`` is machine-readable, ``message`` user-safe."""

    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


@dataclass
class ToolContext:
    """Everything a tool may touch. ``customer_id`` comes from the authenticated session,
    never from model-supplied arguments, so the model cannot act for another customer."""

    customer_id: str
    session_id: str
    repo: Repository
    clock: Clock
    faq: FAQIndex
    refund_policy: RefundPolicy = field(default_factory=RefundPolicy)
    address_policy: AddressPolicy = field(default_factory=AddressPolicy)
    events: list[dict[str, Any]] = field(default_factory=list)
    handoff_reason: str | None = None

    def flag(self, guardrail: str, **detail: Any) -> None:
        self.events.append({"guardrail": guardrail, **detail})

    def request_handoff(self, reason: str) -> None:
        self.handoff_reason = self.handoff_reason or reason


Handler = Callable[[ToolContext, Any], dict[str, Any]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    handler: Handler
    mutates: bool = False

    def schema(self) -> dict[str, Any]:
        params = self.args.model_json_schema()
        params.pop("title", None)
        return {"name": self.name, "description": self.description, "input_schema": params}


@dataclass
class ToolOutcome:
    name: str
    arguments: dict[str, Any]
    status: str  # ok | error | invalid_arguments | unknown_tool
    result: dict[str, Any]
    duration_ms: float
    guardrails: list[dict[str, Any]] = field(default_factory=list)


class ToolRegistry:
    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {t.name: t for t in tools}

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [t.schema() for t in self._tools.values()]

    def call(self, ctx: ToolContext, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        start = time.perf_counter()
        before = len(ctx.events)

        def done(status: str, result: dict[str, Any]) -> ToolOutcome:
            return ToolOutcome(
                name,
                arguments,
                status,
                result,
                round((time.perf_counter() - start) * 1000, 3),
                ctx.events[before:],
            )

        tool = self._tools.get(name)
        if tool is None:
            return done("unknown_tool", {"error": "unknown_tool", "message": f"No tool {name!r}."})
        try:
            args = tool.args.model_validate(arguments)
        except ValidationError as exc:
            problems = [
                {"field": ".".join(str(p) for p in e["loc"]) or "(root)", "problem": e["msg"]}
                for e in exc.errors()
            ]
            ctx.flag("argument_validation", tool=name, problems=problems)
            return done("invalid_arguments", {"error": "invalid_arguments", "problems": problems})
        try:
            return done("ok", tool.handler(ctx, args))
        except ToolError as exc:
            return done("error", {"error": exc.code, "message": exc.message, **exc.extra})
