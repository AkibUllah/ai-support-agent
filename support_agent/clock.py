"""Injectable clock so refund-window rules are testable and evals are deterministic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol

DHAKA = timezone(timedelta(hours=6), "Asia/Dhaka")


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FixedClock:
    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FixedClock needs an aware datetime")
        self._at = at

    def now(self) -> datetime:
        return self._at

    def advance(self, **delta: float) -> None:
        self._at = self._at + timedelta(**delta)


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
