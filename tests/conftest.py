from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from support_agent.clock import FixedClock
from support_agent.config import Settings
from support_agent.domain.db import Database
from support_agent.evals.runner import EVAL_NOW
from support_agent.llm.base import LLM
from support_agent.service import SupportService
from support_agent.tools.base import ToolContext


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, app_env="test", database_path=":memory:", log_level="WARNING")


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(EVAL_NOW)


@pytest.fixture
def make_service(settings, clock) -> Callable[..., SupportService]:
    def factory(llm: LLM | None = None, **overrides: Any) -> SupportService:
        s = settings.model_copy(update=overrides) if overrides else settings
        return SupportService(s, Database(":memory:"), clock, llm)

    return factory


@pytest.fixture
def service(make_service) -> SupportService:
    return make_service()


@pytest.fixture
def chat(service):
    """Send messages as a customer; returns (send, session_id)."""

    def start(customer_id: str = "C001"):
        session_id = service.start_session(customer_id).session_id

        def send(text: str):
            return service.send(service.repo.get_session(session_id), text)

        return send, session_id

    return start


@pytest.fixture
def ctx(service, clock):
    def make(customer_id: str = "C001") -> ToolContext:
        return ToolContext(
            customer_id=customer_id,
            session_id="s-test",
            repo=service.repo,
            clock=clock,
            faq=service.faq,
        )

    return make
