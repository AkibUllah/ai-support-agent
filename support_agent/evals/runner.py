"""Run scripted conversations against a fresh seeded database and check expectations."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from support_agent.clock import FixedClock
from support_agent.config import Settings
from support_agent.domain.db import Database
from support_agent.llm.base import LLM
from support_agent.service import SupportService, build_llm

# Every scenario runs at this instant so "delivered 6 days 23 hours ago" is stable.
EVAL_NOW = datetime(2026, 3, 15, 6, 0, tzinfo=timezone.utc)

TURN_KEYS = {"tools", "status", "guardrails", "reply_contains", "reply_not_contains", "state"}
OUTCOME_KEYS = {
    "refunds",
    "tickets",
    "address_contains",
    "address_unchanged",
    "audit",
    "audit_absent",
    "never_called",
}


class ScenarioError(ValueError):
    """The scenario file is malformed."""


@dataclass
class TurnRecord:
    user: str
    reply: str
    state: str
    trace: list[dict[str, Any]]
    latency_ms: float


@dataclass
class ScenarioResult:
    id: str
    category: str
    customer: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    turns: list[TurnRecord] = field(default_factory=list)

    @property
    def tool_calls(self) -> int:
        return sum(1 for t in self.turns for s in t.trace if s["type"] == "tool")

    def guardrails(self) -> list[str]:
        names: list[str] = []
        for t in self.turns:
            names.extend(_guardrails_in(t.trace))
        return names


def _guardrails_in(trace: list[dict[str, Any]]) -> list[str]:
    names = []
    for step in trace:
        if step["type"] == "guardrail":
            names.append(step["name"])
        for g in step.get("guardrails", []):
            names.append(g["guardrail"])
    return names


def load_scenarios(path: str | Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ScenarioError("scenario file must contain a list")
    ids = set()
    for sc in data:
        for key in ("id", "category", "customer", "turns"):
            if key not in sc:
                raise ScenarioError(f"scenario {sc.get('id', '?')} is missing {key!r}")
        if sc["id"] in ids:
            raise ScenarioError(f"duplicate scenario id {sc['id']}")
        ids.add(sc["id"])
        for turn in sc["turns"]:
            unknown = set(turn.get("expect", {})) - TURN_KEYS
            if unknown:
                raise ScenarioError(f"{sc['id']}: unknown turn expectation(s) {sorted(unknown)}")
        unknown = set(sc.get("outcome", {})) - OUTCOME_KEYS
        if unknown:
            raise ScenarioError(f"{sc['id']}: unknown outcome check(s) {sorted(unknown)}")
    return data


def _check_turn(n: int, exp: dict[str, Any], rec: TurnRecord) -> list[str]:
    fails: list[str] = []
    tools = [s for s in rec.trace if s["type"] == "tool"]
    names = [s["name"] for s in tools]
    if "tools" in exp and names != exp["tools"]:
        fails.append(f"turn {n}: tools {names} != expected {exp['tools']}")
    for tool, status in exp.get("status", {}).items():
        got = [s["status"] for s in tools if s["name"] == tool]
        if status not in got:
            fails.append(f"turn {n}: {tool} status {got} does not include {status}")
    fired = _guardrails_in(rec.trace)
    for g in exp.get("guardrails", []):
        if g not in fired:
            fails.append(f"turn {n}: guardrail {g!r} did not fire (fired: {fired})")
    reply = rec.reply.lower()
    for s in exp.get("reply_contains", []):
        if str(s).lower() not in reply:
            fails.append(f"turn {n}: reply missing {s!r}")
    for s in exp.get("reply_not_contains", []):
        if str(s).lower() in reply:
            fails.append(f"turn {n}: reply must not contain {s!r}")
    if "state" in exp and rec.state != exp["state"]:
        fails.append(f"turn {n}: state {rec.state!r} != {exp['state']!r}")
    return fails


def _check_outcome(
    out: dict[str, Any],
    svc: SupportService,
    result: ScenarioResult,
    addresses_before: dict[str, str],
    tickets_before: int,
) -> list[str]:
    fails: list[str] = []
    repo = svc.repo
    for order_id, expected in out.get("refunds", {}).items():
        statuses = [r["status"] for r in repo.list_refunds(order_id) if r["id"] != "RF-0001"]
        if expected == "none" and statuses:
            fails.append(f"outcome: expected no refund on {order_id}, found {statuses}")
        elif expected != "none" and expected not in statuses:
            fails.append(f"outcome: expected {expected} refund on {order_id}, found {statuses}")
    if "tickets" in out:
        created = len(repo.list_tickets()) - tickets_before
        if created != out["tickets"]:
            fails.append(f"outcome: {created} tickets created, expected {out['tickets']}")
    for order_id, needle in out.get("address_contains", {}).items():
        addr = repo.get_order(order_id)["shipping_address"]  # type: ignore[index]
        if needle not in addr:
            fails.append(f"outcome: {order_id} address {addr!r} lacks {needle!r}")
    for order_id in out.get("address_unchanged", []):
        if repo.get_order(order_id)["shipping_address"] != addresses_before[order_id]:  # type: ignore[index]
            fails.append(f"outcome: {order_id} address changed")
    events = {e["event"] for e in repo.audit_events()}
    for event in out.get("audit", []):
        if event not in events:
            fails.append(f"outcome: audit event {event!r} missing")
    for event in out.get("audit_absent", []):
        if event in events:
            fails.append(f"outcome: unexpected audit event {event!r}")
    called = {s["name"] for t in result.turns for s in t.trace if s["type"] == "tool"}
    for tool in out.get("never_called", []):
        if tool in called:
            fails.append(f"outcome: {tool} must never be called")
    return fails


def run_scenario(
    sc: dict[str, Any], settings: Settings, llm_factory: Callable[[], LLM]
) -> ScenarioResult:
    svc = SupportService(settings, Database(":memory:"), FixedClock(EVAL_NOW), llm_factory())
    addresses_before = {
        o["id"]: o["shipping_address"]
        for o in svc.db.query("SELECT id, shipping_address FROM orders")
    }
    tickets_before = len(svc.repo.list_tickets())
    session_id = svc.start_session(sc["customer"]).session_id
    result = ScenarioResult(sc["id"], sc["category"], sc["customer"], passed=True)
    for n, turn in enumerate(sc["turns"], start=1):
        session = svc.repo.get_session(session_id)
        start = time.perf_counter()
        out = svc.send(session, turn["user"])  # type: ignore[arg-type]
        rec = TurnRecord(
            turn["user"],
            out.reply,
            out.state,
            out.trace,
            round((time.perf_counter() - start) * 1000, 2),
        )
        result.turns.append(rec)
        result.failures.extend(_check_turn(n, turn.get("expect", {}), rec))
    result.failures.extend(
        _check_outcome(sc.get("outcome", {}), svc, result, addresses_before, tickets_before)
    )
    result.passed = not result.failures
    svc.db.close()
    return result


def run_all(
    scenarios: list[dict[str, Any]],
    settings: Settings,
    llm_factory: Callable[[], LLM] | None = None,
) -> list[ScenarioResult]:
    eval_settings = settings.model_copy(
        update={"database_path": ":memory:", "seed_on_startup": True}
    )
    factory = llm_factory or (lambda: build_llm(eval_settings))
    return [run_scenario(sc, eval_settings, factory) for sc in scenarios]


def summary_table(results: list[ScenarioResult]) -> str:
    cats: dict[str, list[ScenarioResult]] = {}
    for r in results:
        cats.setdefault(r.category, []).append(r)
    lines = [
        "| Category | Scenarios | Passed | Pass rate | Tool calls | Guardrail events |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for cat, rs in cats.items():
        passed = sum(r.passed for r in rs)
        lines.append(
            f"| {cat} | {len(rs)} | {passed} | {passed / len(rs):.0%} | "
            f"{sum(r.tool_calls for r in rs)} | {sum(len(r.guardrails()) for r in rs)} |"
        )
    total = sum(r.passed for r in results)
    lines.append(
        f"| **total** | **{len(results)}** | **{total}** | "
        f"**{total / len(results):.1%}** | **{sum(r.tool_calls for r in results)}** | "
        f"**{sum(len(r.guardrails()) for r in results)}** |"
    )
    return "\n".join(lines)


def guardrail_table(results: list[ScenarioResult]) -> str:
    counts = Counter(g for r in results for g in r.guardrails())
    lines = ["| Guardrail | Times fired |", "|---|---:|"]
    lines += [f"| {name} | {n} |" for name, n in counts.most_common()]
    return "\n".join(lines)


def transcripts(results: list[ScenarioResult]) -> list[dict[str, Any]]:
    return [
        {
            "id": r.id,
            "category": r.category,
            "customer": r.customer,
            "passed": r.passed,
            "failures": r.failures,
            "turns": [
                {"user": t.user, "reply": t.reply, "state": t.state, "trace": t.trace}
                for t in r.turns
            ],
        }
        for r in results
    ]
