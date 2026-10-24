"""Business rules, enforced in code no matter what the model asks for.

The model proposes an action through a tool; the policy decides. A prompt can make a
model *ask* for a ৳12,500 refund, but only this module can approve one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from support_agent.clock import parse_ts

Action = Literal["approve", "escalate", "deny"]
ADDRESS_EDITABLE = ("placed", "packed")


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: str
    message: str
    amount: int = 0

    @property
    def allowed(self) -> bool:
        return self.action != "deny"


@dataclass(frozen=True)
class RefundPolicy:
    window_days: int = 7
    auto_approve_limit: int = 5000

    def evaluate(
        self, order: dict[str, Any], amount: int | None, already_refunded: int, now: datetime
    ) -> Decision:
        status = order["status"]
        if status == "cancelled":
            return Decision(
                "deny",
                "order_cancelled",
                "The order was cancelled; any prepaid amount is returned automatically.",
            )
        if status != "delivered" or not order.get("delivered_at"):
            return Decision(
                "deny",
                "not_delivered",
                "Refunds open once an order is delivered. Undelivered orders can be "
                "cancelled through a support ticket.",
            )
        delivered_at = parse_ts(order["delivered_at"])
        if now - delivered_at > timedelta(days=self.window_days):
            return Decision(
                "deny",
                "outside_window",
                f"Refunds must be requested within {self.window_days} days of delivery.",
            )
        refundable = order["total"] - already_refunded
        if refundable <= 0:
            return Decision(
                "deny", "already_refunded", "This order has already been refunded in full."
            )
        requested = refundable if amount is None else amount
        if requested <= 0:
            return Decision("deny", "invalid_amount", "The refund amount must be positive.")
        if requested > refundable:
            return Decision(
                "deny",
                "exceeds_refundable",
                f"At most ৳{refundable:,} can be refunded for this order.",
                refundable,
            )
        if requested <= self.auto_approve_limit:
            return Decision(
                "approve",
                "auto_approved",
                f"Refunds up to ৳{self.auto_approve_limit:,} are approved automatically.",
                requested,
            )
        return Decision(
            "escalate",
            "needs_review",
            f"Refunds above ৳{self.auto_approve_limit:,} are reviewed by a person.",
            requested,
        )


@dataclass(frozen=True)
class AddressPolicy:
    def evaluate(self, order: dict[str, Any]) -> Decision:
        if order["status"] in ADDRESS_EDITABLE:
            return Decision("approve", "editable", "The address can still be changed.")
        if order["status"] == "cancelled":
            return Decision("deny", "order_cancelled", "The order was cancelled.")
        return Decision(
            "deny",
            "already_dispatched",
            "The order has left the warehouse, so the courier address cannot be "
            "changed. The rider can be contacted from the tracking page.",
        )
