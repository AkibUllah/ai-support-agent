"""Prompt-injection heuristics, tool-output sanitising and PII redaction.

Heuristics are deliberately conservative pattern lists: they will not catch everything,
which is why authorisation and policy are enforced in code rather than trusted to the
model. Their job is to stop the obvious attempts early and leave an audit trail.
"""

from __future__ import annotations

import logging
import re
from typing import Any

INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "override_instructions",
        re.compile(
            r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|your|the)\b"
            r"[^.\n]{0,20}\b(instructions?|rules?|polic(y|ies)|prompt)",
            re.I,
        ),
    ),
    (
        "role_switch",
        re.compile(
            r"\b(you are now|act as|pretend to be|switch to)\b[^.\n]{0,30}"
            r"\b(admin|administrator|developer|system|root|dan|unrestricted)\b",
            re.I,
        ),
    ),
    ("admin_mode", re.compile(r"\b(admin|developer|god|debug|jailbreak)\s+mode\b", re.I)),
    (
        "prompt_exfiltration",
        re.compile(
            r"\b(reveal|show|print|repeat|leak)\b[^.\n]{0,30}\b(system prompt|hidden prompt|your instructions)",
            re.I,
        ),
    ),
    (
        "fake_system_block",
        re.compile(r"(<\|?(system|im_start)\|?>|\[/?(system|inst)\]|^\s*system\s*:)", re.I | re.M),
    ),
    ("bulk_refund", re.compile(r"\brefunds?\b[^.\n]{0,30}\b(every|all)\s+orders?\b", re.I)),
    (
        "bn_override",
        re.compile(r"(আগের|পূর্বের)\s+(সব\s+)?(নির্দেশ|নির্দেশনা|নিয়ম)[^\n]{0,20}(ভুলে|উপেক্ষা|বাদ)"),
    ),
]

REMOVED = "[removed: text that looked like instructions]"

_PHONE_RE = re.compile(r"(?<!\d)(?:\+?88)?01[3-9]\d{2}[-\s]?\d{6}(?!\d)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


def detect_injection(text: str) -> list[str]:
    """Names of the injection patterns ``text`` matches (empty list = clean)."""
    return [name for name, pattern in INJECTION_PATTERNS if pattern.search(text)]


def sanitize_tool_output(value: Any) -> tuple[Any, list[str]]:
    """Replace instruction-like strings inside a tool result before the model sees it."""
    flags: list[str] = []

    def walk(v: Any) -> Any:
        if isinstance(v, str):
            hits = detect_injection(v)
            if hits:
                flags.extend(hits)
                return REMOVED
            return v
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v

    return walk(value), sorted(set(flags))


def redact_pii(text: str) -> str:
    """Mask phone numbers, emails and card-like digit runs (for logs, not for the user)."""
    text = _EMAIL_RE.sub("[email]", text)
    text = _PHONE_RE.sub(lambda m: m.group(0)[:3] + "*****" + m.group(0)[-3:], text)
    return _CARD_RE.sub("[card]", text)


class PIIRedactingFilter(logging.Filter):
    """Logging filter that redacts the formatted message of every record it sees."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - malformed record, leave untouched
            return True
        record.msg = redact_pii(message)
        record.args = ()
        return True
