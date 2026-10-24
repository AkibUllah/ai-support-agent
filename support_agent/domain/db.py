"""SQLite connection wrapper and schema.

One connection per process with a lock: SQLite serialises writes anyway, and this keeps
the demo dependency-free. ``:memory:`` databases are used by tests and evals.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT NOT NULL,
    district TEXT NOT NULL,
    default_address TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    status TEXT NOT NULL CHECK (status IN ('placed','packed','dispatched','delivered','cancelled')),
    placed_at TEXT NOT NULL,
    dispatched_at TEXT,
    delivered_at TEXT,
    total INTEGER NOT NULL CHECK (total >= 0),
    payment_method TEXT NOT NULL,
    shipping_address TEXT NOT NULL,
    delivery_note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_orders_customer ON orders(customer_id, placed_at);
CREATE TABLE IF NOT EXISTS order_items (
    order_id TEXT NOT NULL REFERENCES orders(id),
    product TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price INTEGER NOT NULL CHECK (unit_price >= 0)
);
CREATE TABLE IF NOT EXISTS shipments (
    order_id TEXT PRIMARY KEY REFERENCES orders(id),
    courier TEXT NOT NULL,
    tracking_no TEXT NOT NULL,
    eta TEXT,
    events TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS refunds (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    amount INTEGER NOT NULL CHECK (amount > 0),
    status TEXT NOT NULL CHECK (status IN ('approved','pending_review')),
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    ticket_id TEXT
);
CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    order_id TEXT,
    category TEXT NOT NULL,
    summary TEXT NOT NULL,
    priority TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active','handoff','closed')),
    handoff_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    user_text TEXT NOT NULL,
    reply TEXT NOT NULL,
    trace TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    customer_id TEXT,
    event TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            # WAL + NORMAL sync: durable across app crashes, one fsync per checkpoint instead of
            # per statement. Keeps a chat turn (5-8 small writes) in the low milliseconds.
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
            self._conn.execute("PRAGMA busy_timeout = 5000")
        self._lock = threading.RLock()
        self._conn.executescript(SCHEMA)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, params)
            return cur.lastrowid or 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def is_empty(self) -> bool:
        return self.one("SELECT COUNT(*) AS n FROM customers")["n"] == 0  # type: ignore[index]

    def close(self) -> None:
        self._conn.close()
