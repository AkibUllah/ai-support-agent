"""Settings from environment variables (prefix ``AGENT_``) or a ``.env`` file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_", env_file=".env", extra="ignore")

    app_env: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # SQLite file for the shop domain + sessions. ":memory:" is used by tests.
    database_path: str = str(PROJECT_ROOT / "data" / "shop.db")
    seed_on_startup: bool = True
    faq_path: Path = PROJECT_ROOT / "data" / "faq.json"

    llm_provider: Literal["fake", "openai", "anthropic"] = "fake"
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    llm_timeout_seconds: float = 30.0

    max_steps: int = Field(default=6, ge=1, le=20)
    max_tool_calls_per_turn: int = Field(default=8, ge=1, le=50)
    max_message_chars: int = Field(default=2000, ge=50, le=20000)
    session_ttl_hours: int = Field(default=24, ge=1)

    # Soft guardrails can be switched off for ablation runs (agent-eval --disable ...).
    # Ownership checks and the policy engine are not configurable: they are the boundary.
    guard_input_injection: bool = True
    guard_tool_output: bool = True

    # Refund policy (amounts in BDT)
    refund_window_days: int = 7
    refund_auto_approve_limit: int = 5000

    admin_api_key: str = Field(default="change-me-admin-key", min_length=8)
    ui_dir: Path = PROJECT_ROOT / "ui" / "dist"

    def llm_url(self) -> str:
        return self.llm_base_url or DEFAULT_BASE_URLS.get(self.llm_provider, "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
