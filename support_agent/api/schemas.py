"""HTTP request/response models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CustomerOut(BaseModel):
    id: str
    name: str
    district: str
    phone_masked: str


class SessionCreate(BaseModel):
    customer_id: str = Field(pattern=r"^C\d{3}$", description="Demo login: pick a seeded customer")


class SessionCreated(BaseModel):
    session_id: str
    token: str = Field(description="Send as 'Authorization: Bearer <token>'")
    customer: CustomerOut
    state: Literal["active", "handoff", "closed"]


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class TurnOut(BaseModel):
    turn_id: int
    reply: str
    state: str
    trace: list[dict[str, Any]]


class TurnHistory(BaseModel):
    turn_id: int
    user: str
    reply: str
    trace: list[dict[str, Any]]
    created_at: str


class SessionOut(BaseModel):
    session_id: str
    customer: CustomerOut
    state: str
    handoff_reason: str | None
    turns: list[TurnHistory]


class HealthOut(BaseModel):
    status: Literal["ok"]
    version: str
    llm_provider: str
    tools: list[str]
