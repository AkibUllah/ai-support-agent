"""Composition root: wires settings, database, clock, tools and model into sessions."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from support_agent.agent import Agent, TurnResult
from support_agent.clock import Clock, SystemClock, parse_ts
from support_agent.config import Settings
from support_agent.domain.db import Database
from support_agent.domain.repository import Repository
from support_agent.domain.seed import seed
from support_agent.faq import FAQIndex
from support_agent.llm.anthropic import AnthropicLLM
from support_agent.llm.base import LLM
from support_agent.llm.fake import ScriptedPolicyModel
from support_agent.llm.openai_compat import OpenAICompatibleLLM
from support_agent.tools import build_registry


class AuthError(Exception):
    """Unknown session, wrong token or expired session."""


def build_llm(settings: Settings) -> LLM:
    if settings.llm_provider == "fake":
        return ScriptedPolicyModel()
    if not settings.llm_model:
        raise ValueError(f"AGENT_LLM_MODEL is required for provider {settings.llm_provider!r}")
    if settings.llm_provider == "anthropic":
        return AnthropicLLM(
            settings.llm_url(),
            settings.llm_model,
            settings.llm_api_key,
            timeout=settings.llm_timeout_seconds,
        )
    return OpenAICompatibleLLM(
        settings.llm_url(),
        settings.llm_model,
        settings.llm_api_key,
        timeout=settings.llm_timeout_seconds,
    )


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class NewSession:
    session_id: str
    token: str
    customer: dict[str, Any]


class SupportService:
    def __init__(
        self,
        settings: Settings,
        db: Database | None = None,
        clock: Clock | None = None,
        llm: LLM | None = None,
    ) -> None:
        self.settings = settings
        self.clock = clock or SystemClock()
        self.db = db or Database(settings.database_path)
        if settings.seed_on_startup:
            seed(self.db, self.clock.now())
        self.repo = Repository(self.db)
        self.faq = FAQIndex.load(settings.faq_path)
        self.tools = build_registry()
        self.agent = Agent(
            llm or build_llm(settings), self.tools, self.repo, self.clock, settings, self.faq
        )

    def start_session(self, customer_id: str) -> NewSession:
        customer = self.repo.get_customer(customer_id)
        if customer is None:
            raise LookupError(customer_id)
        session_id, token = uuid.uuid4().hex, secrets.token_urlsafe(24)
        self.repo.create_session(session_id, _hash(token), customer_id, self.clock.now())
        return NewSession(session_id, token, customer)

    def authenticate(self, session_id: str, token: str) -> dict[str, Any]:
        session = self.repo.get_session(session_id)
        if session is None or not hmac.compare_digest(session["token_hash"], _hash(token)):
            raise AuthError("invalid session or token")
        age = self.clock.now() - parse_ts(session["created_at"])
        if age > timedelta(hours=self.settings.session_ttl_hours):
            raise AuthError("session expired")
        return session

    def send(self, session: dict[str, Any], text: str) -> TurnResult:
        return self.agent.handle(session, text)
