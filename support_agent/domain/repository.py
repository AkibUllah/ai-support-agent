"""All SQL lives here; tools and the API talk to this repository only."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from support_agent.clock import iso
from support_agent.domain.db import Database


class Repository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- customers ------------------------------------------------------------------
    def get_customer(self, customer_id: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM customers WHERE id = ?", (customer_id,))

    def list_customers(self) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM customers ORDER BY id")

    # -- orders ---------------------------------------------------------------------
    def get_order(self, order_id: str) -> dict[str, Any] | None:
        order = self.db.one("SELECT * FROM orders WHERE id = ?", (order_id,))
        if order is None:
            return None
        order["items"] = self.db.query(
            "SELECT product, quantity, unit_price FROM order_items WHERE order_id = ?",
            (order_id,),
        )
        shipment = self.db.one("SELECT * FROM shipments WHERE order_id = ?", (order_id,))
        if shipment:
            shipment["events"] = json.loads(shipment["events"])
        order["shipment"] = shipment
        order["refunds"] = self.db.query(
            "SELECT id, amount, status, created_at FROM refunds WHERE order_id = ? ORDER BY id",
            (order_id,),
        )
        return order

    def list_orders(self, customer_id: str, limit: int = 5) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT id, status, placed_at, delivered_at, total, payment_method FROM orders "
            "WHERE customer_id = ? ORDER BY placed_at DESC LIMIT ?",
            (customer_id, limit),
        )

    def refunded_total(self, order_id: str) -> int:
        row = self.db.one(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM refunds WHERE order_id = ?", (order_id,)
        )
        return int(row["total"]) if row else 0

    def update_shipping_address(self, order_id: str, address: str) -> None:
        self.db.execute("UPDATE orders SET shipping_address = ? WHERE id = ?", (address, order_id))

    # -- refunds & tickets ----------------------------------------------------------
    def _next_id(self, table: str, prefix: str) -> str:
        row = self.db.one(f"SELECT COUNT(*) AS n FROM {table}")  # noqa: S608 - fixed names
        return f"{prefix}-{(row['n'] if row else 0) + 1:04d}"

    def create_refund(
        self,
        order_id: str,
        amount: int,
        status: str,
        reason: str,
        now: datetime,
        ticket_id: str | None = None,
    ) -> str:
        with self.db.transaction():
            rid = self._next_id("refunds", "RF")
            self.db.execute(
                "INSERT INTO refunds VALUES (?,?,?,?,?,?,?)",
                (rid, order_id, amount, status, reason, iso(now), ticket_id),
            )
        return rid

    def create_ticket(
        self,
        customer_id: str,
        order_id: str | None,
        category: str,
        summary: str,
        priority: str,
        now: datetime,
    ) -> str:
        with self.db.transaction():
            tid = self._next_id("tickets", "TK")
            self.db.execute(
                "INSERT INTO tickets (id, customer_id, order_id, category, summary, priority, "
                "created_at) VALUES (?,?,?,?,?,?,?)",
                (tid, customer_id, order_id, category, summary, priority, iso(now)),
            )
        return tid

    def list_tickets(self, customer_id: str | None = None) -> list[dict[str, Any]]:
        if customer_id:
            return self.db.query(
                "SELECT * FROM tickets WHERE customer_id = ? ORDER BY id", (customer_id,)
            )
        return self.db.query("SELECT * FROM tickets ORDER BY id")

    def list_refunds(self, order_id: str | None = None) -> list[dict[str, Any]]:
        if order_id:
            return self.db.query(
                "SELECT * FROM refunds WHERE order_id = ? ORDER BY id", (order_id,)
            )
        return self.db.query("SELECT * FROM refunds ORDER BY id")

    # -- sessions -------------------------------------------------------------------
    def create_session(
        self, session_id: str, token_hash: str, customer_id: str, now: datetime
    ) -> None:
        self.db.execute(
            "INSERT INTO sessions (id, token_hash, customer_id, created_at, updated_at) "
            "VALUES (?,?,?,?,?)",
            (session_id, token_hash, customer_id, iso(now), iso(now)),
        )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM sessions WHERE id = ?", (session_id,))

    def set_session_state(
        self, session_id: str, state: str, now: datetime, reason: str | None = None
    ) -> None:
        self.db.execute(
            "UPDATE sessions SET state = ?, handoff_reason = COALESCE(?, handoff_reason), "
            "updated_at = ? WHERE id = ?",
            (state, reason, iso(now), session_id),
        )

    def sessions_in_state(self, state: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT id, customer_id, state, handoff_reason, updated_at FROM sessions "
            "WHERE state = ? ORDER BY updated_at DESC",
            (state,),
        )

    def append_messages(
        self, session_id: str, messages: list[dict[str, Any]], now: datetime
    ) -> None:
        with self.db.transaction():
            for message in messages:
                self.db.execute(
                    "INSERT INTO messages (session_id, body, created_at) VALUES (?,?,?)",
                    (session_id, json.dumps(message, ensure_ascii=False), iso(now)),
                )

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT body FROM messages WHERE session_id = ? ORDER BY id", (session_id,)
        )
        return [json.loads(r["body"]) for r in rows]

    def add_turn(
        self,
        session_id: str,
        user_text: str,
        reply: str,
        trace: list[dict[str, Any]],
        now: datetime,
    ) -> int:
        return self.db.execute(
            "INSERT INTO turns (session_id, user_text, reply, trace, created_at) "
            "VALUES (?,?,?,?,?)",
            (session_id, user_text, reply, json.dumps(trace, ensure_ascii=False), iso(now)),
        )

    def list_turns(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT id, user_text, reply, trace, created_at FROM turns WHERE session_id = ? "
            "ORDER BY id",
            (session_id,),
        )
        for r in rows:
            r["trace"] = json.loads(r["trace"])
        return rows

    # -- audit ----------------------------------------------------------------------
    def audit(
        self,
        event: str,
        detail: dict[str, Any],
        now: datetime,
        session_id: str | None = None,
        customer_id: str | None = None,
    ) -> None:
        self.db.execute(
            "INSERT INTO audit_events (session_id, customer_id, event, detail, created_at) "
            "VALUES (?,?,?,?,?)",
            (session_id, customer_id, event, json.dumps(detail, ensure_ascii=False), iso(now)),
        )

    def audit_events(self, event: str | None = None) -> list[dict[str, Any]]:
        if event:
            return self.db.query("SELECT * FROM audit_events WHERE event = ? ORDER BY id", (event,))
        return self.db.query("SELECT * FROM audit_events ORDER BY id")
