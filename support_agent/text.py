"""Small text helpers shared by the agent and the offline model."""

from __future__ import annotations

_CURRENCY = {"\u09f2", "\u09f3"}  # ৲ ৳ live in the Bengali block but are not Bangla text


def is_bangla(text: str) -> bool:
    """True if the text contains Bangla letters (the taka sign alone does not count)."""
    return any("\u0980" <= ch <= "\u09ff" and ch not in _CURRENCY for ch in text)
