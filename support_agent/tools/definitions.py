"""The eight support tools. Handlers validate ownership first, then apply policy."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

from support_agent.tools.base import Tool, ToolContext, ToolError, ToolRegistry

OrderId = Annotated[
    str,
    BeforeValidator(lambda v: v.strip().upper() if isinstance(v, str) else v),
    StringConstraints(pattern=r"^HO-\d{5}$"),
    Field(description="Order number, e.g. HO-10021"),
]


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OrderArgs(_Args):
    order_id: OrderId


class RecentOrdersArgs(_Args):
    limit: int = Field(default=5, ge=1, le=10)


class RefundArgs(_Args):
    order_id: OrderId
    reason: str = Field(min_length=3, max_length=300, description="Customer's reason, briefly")
    amount: int | None = Field(
        default=None,
        gt=0,
        le=1_000_000,
        description="Refund amount in BDT; omit for the full refundable amount",
    )


class AddressArgs(_Args):
    order_id: OrderId
    new_address: str = Field(
        min_length=15,
        max_length=200,
        description=(
            "Full delivery address including area and city, e.g. 'House 9, Road 2, Banani, Dhaka'"
        ),
    )

    @field_validator("new_address")
    @classmethod
    def _has_letters(cls, v: str) -> str:
        if sum(ch.isalpha() for ch in v) < 8:
            raise ValueError("address must contain area and city names")
        return " ".join(v.split())


class TicketArgs(_Args):
    category: Literal[
        "delivery", "refund", "product", "payment", "account", "cancellation", "other"
    ]
    summary: str = Field(min_length=10, max_length=500)
    order_id: OrderId | None = None
    priority: Literal["low", "normal", "high"] = "normal"


class FAQArgs(_Args):
    query: str = Field(min_length=2, max_length=200)


class HandoffArgs(_Args):
    reason: str = Field(min_length=3, max_length=300)


def _owned_order(ctx: ToolContext, order_id: str) -> dict[str, Any]:
    """Fetch an order only if it belongs to the session's customer.

    Another customer's order is reported exactly like a missing one (no existence
    oracle), and the attempt is written to the audit log.
    """
    order = ctx.repo.get_order(order_id)
    if order is None or order["customer_id"] != ctx.customer_id:
        if order is not None:
            ctx.flag("ownership_check", order_id=order_id, blocked=True)
            ctx.repo.audit(
                "cross_customer_access",
                {"order_id": order_id},
                ctx.clock.now(),
                session_id=ctx.session_id,
                customer_id=ctx.customer_id,
            )
        raise ToolError("order_not_found", f"No order {order_id} was found on this account.")
    return order


def lookup_order(ctx: ToolContext, args: OrderArgs) -> dict[str, Any]:
    o = _owned_order(ctx, args.order_id)
    return {
        "order_id": o["id"],
        "status": o["status"],
        "placed_at": o["placed_at"],
        "delivered_at": o["delivered_at"],
        "total_bdt": o["total"],
        "payment_method": o["payment_method"],
        "items": [
            {"product": i["product"], "quantity": i["quantity"], "unit_price_bdt": i["unit_price"]}
            for i in o["items"]
        ],
        "shipping_address": o["shipping_address"],
        "delivery_note": o["delivery_note"],
        "refunds": [
            {"id": r["id"], "amount_bdt": r["amount"], "status": r["status"]} for r in o["refunds"]
        ],
    }


def track_shipment(ctx: ToolContext, args: OrderArgs) -> dict[str, Any]:
    o = _owned_order(ctx, args.order_id)
    s = o["shipment"]
    if s is None:
        return {
            "order_id": o["id"],
            "status": o["status"],
            "shipment": None,
            "message": "Not handed to a courier yet."
            if o["status"] != "cancelled"
            else "The order was cancelled.",
        }
    events = s["events"]
    return {
        "order_id": o["id"],
        "status": o["status"],
        "courier": s["courier"],
        "tracking_no": s["tracking_no"],
        "eta": s["eta"],
        "latest_event": events[-1] if events else None,
        "events": events,
    }


def list_recent_orders(ctx: ToolContext, args: RecentOrdersArgs) -> dict[str, Any]:
    rows = ctx.repo.list_orders(ctx.customer_id, args.limit)
    return {
        "orders": [
            {
                "order_id": r["id"],
                "status": r["status"],
                "placed_at": r["placed_at"],
                "total_bdt": r["total"],
            }
            for r in rows
        ]
    }


def initiate_refund(ctx: ToolContext, args: RefundArgs) -> dict[str, Any]:
    o = _owned_order(ctx, args.order_id)
    now = ctx.clock.now()
    decision = ctx.refund_policy.evaluate(o, args.amount, ctx.repo.refunded_total(o["id"]), now)
    ctx.flag("refund_policy", order_id=o["id"], action=decision.action, reason=decision.reason)
    if decision.action == "deny":
        return {
            "status": "denied",
            "order_id": o["id"],
            "reason": decision.reason,
            "message": decision.message,
        }
    if decision.action == "approve":
        rid = ctx.repo.create_refund(o["id"], decision.amount, "approved", args.reason, now)
        return {
            "status": "approved",
            "order_id": o["id"],
            "refund_id": rid,
            "amount_bdt": decision.amount,
            "payment_method": o["payment_method"],
            "message": decision.message,
        }
    tid = ctx.repo.create_ticket(
        ctx.customer_id,
        o["id"],
        "refund",
        f"Refund review: ৳{decision.amount:,} for {o['id']}. Reason: {args.reason}",
        "high",
        now,
    )
    rid = ctx.repo.create_refund(o["id"], decision.amount, "pending_review", args.reason, now, tid)
    ctx.request_handoff(f"refund of ৳{decision.amount:,} on {o['id']} needs review")
    return {
        "status": "pending_review",
        "order_id": o["id"],
        "refund_id": rid,
        "ticket_id": tid,
        "amount_bdt": decision.amount,
        "message": decision.message,
    }


def update_address(ctx: ToolContext, args: AddressArgs) -> dict[str, Any]:
    o = _owned_order(ctx, args.order_id)
    decision = ctx.address_policy.evaluate(o)
    ctx.flag("address_policy", order_id=o["id"], action=decision.action, reason=decision.reason)
    if not decision.allowed:
        return {
            "status": "denied",
            "order_id": o["id"],
            "order_status": o["status"],
            "reason": decision.reason,
            "message": decision.message,
        }
    ctx.repo.update_shipping_address(o["id"], args.new_address)
    return {
        "status": "updated",
        "order_id": o["id"],
        "old_address": o["shipping_address"],
        "new_address": args.new_address,
    }


def create_ticket(ctx: ToolContext, args: TicketArgs) -> dict[str, Any]:
    if args.order_id:
        _owned_order(ctx, args.order_id)
    tid = ctx.repo.create_ticket(
        ctx.customer_id, args.order_id, args.category, args.summary, args.priority, ctx.clock.now()
    )
    return {
        "status": "created",
        "ticket_id": tid,
        "category": args.category,
        "priority": args.priority,
        "order_id": args.order_id,
    }


def search_faq(ctx: ToolContext, args: FAQArgs) -> dict[str, Any]:
    hits = ctx.faq.search(args.query, k=3)
    return {
        "results": [{"id": a.id, "title": a.title, "answer": a.answer, "score": s} for a, s in hits]
    }


def handoff_to_human(ctx: ToolContext, args: HandoffArgs) -> dict[str, Any]:
    tid = ctx.repo.create_ticket(
        ctx.customer_id,
        None,
        "other",
        f"Customer asked for a human: {args.reason}",
        "normal",
        ctx.clock.now(),
    )
    ctx.request_handoff(args.reason)
    return {"status": "handoff", "ticket_id": tid}


def build_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            Tool(
                "lookup_order",
                "Get an order's status, items, totals, address and refunds. "
                "Only orders on the signed-in customer's account are visible.",
                OrderArgs,
                lookup_order,
            ),
            Tool(
                "track_shipment",
                "Courier, tracking number, ETA and delivery events for an order.",
                OrderArgs,
                track_shipment,
            ),
            Tool(
                "list_recent_orders",
                "The signed-in customer's most recent orders, newest first.",
                RecentOrdersArgs,
                list_recent_orders,
            ),
            Tool(
                "initiate_refund",
                "Request a refund for a delivered order. Policy decides: within 7 days of "
                "delivery and up to ৳5,000 is approved automatically; larger amounts go to "
                "human review; otherwise it is denied with a reason.",
                RefundArgs,
                initiate_refund,
                mutates=True,
            ),
            Tool(
                "update_address",
                "Change the delivery address of an order that has not been dispatched yet.",
                AddressArgs,
                update_address,
                mutates=True,
            ),
            Tool(
                "create_ticket",
                "Open a support ticket for issues the tools cannot resolve "
                "(damaged item, cancellation, payment problem).",
                TicketArgs,
                create_ticket,
                mutates=True,
            ),
            Tool(
                "search_faq",
                "Search help-centre articles (delivery, payments, returns, warranty).",
                FAQArgs,
                search_faq,
            ),
            Tool(
                "handoff_to_human",
                "Hand the conversation to a human agent when the customer asks "
                "for one or the issue needs judgement.",
                HandoffArgs,
                handoff_to_human,
                mutates=True,
            ),
        ]
    )
