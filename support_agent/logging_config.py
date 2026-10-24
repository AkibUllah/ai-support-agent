"""Logging setup: one format, PII redaction on every handler."""

from __future__ import annotations

import logging

from support_agent.guardrails import PIIRedactingFilter


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if not any(isinstance(f, PIIRedactingFilter) for h in root.handlers for f in h.filters):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        handler.addFilter(PIIRedactingFilter())
        root.addHandler(handler)
    root.setLevel(level.upper())
