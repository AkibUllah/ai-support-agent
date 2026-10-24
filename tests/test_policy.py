from datetime import timedelta

import pytest

from support_agent.clock import iso
from support_agent.evals.runner import EVAL_NOW
from support_agent.policy import AddressPolicy, RefundPolicy

POLICY = RefundPolicy(window_days=7, auto_approve_limit=5000)


def order(status="delivered", total=2000, delivered_hours_ago=24):
    delivered = (
        iso(EVAL_NOW - timedelta(hours=delivered_hours_ago))
        if delivered_hours_ago is not None
        else None
    )
    return {"status": status, "total": total, "delivered_at": delivered}


@pytest.mark.parametrize(
    ("total", "amount", "action"),
    [
        (4999, None, "approve"),
        (5000, None, "approve"),
        (5001, None, "escalate"),
        (12500, 600, "approve"),
        (12500, 5001, "escalate"),
    ],
)
def test_auto_approve_limit_is_inclusive_and_applies_to_the_refund_amount(total, amount, action):
    assert POLICY.evaluate(order(total=total), amount, 0, EVAL_NOW).action == action


def test_refund_window_boundaries():
    assert POLICY.evaluate(order(delivered_hours_ago=7 * 24), None, 0, EVAL_NOW).action == "approve"
    late = POLICY.evaluate(order(delivered_hours_ago=7 * 24 + 0.02), None, 0, EVAL_NOW)
    assert (late.action, late.reason) == ("deny", "outside_window")


@pytest.mark.parametrize(
    ("o", "reason"),
    [
        (order(status="dispatched", delivered_hours_ago=None), "not_delivered"),
        (order(status="placed", delivered_hours_ago=None), "not_delivered"),
        (order(status="cancelled", delivered_hours_ago=None), "order_cancelled"),
    ],
)
def test_undelivered_orders_are_denied(o, reason):
    decision = POLICY.evaluate(o, None, 0, EVAL_NOW)
    assert (decision.action, decision.reason) == ("deny", reason)


def test_previous_refunds_reduce_the_refundable_amount():
    assert POLICY.evaluate(order(total=2000), None, 2000, EVAL_NOW).reason == "already_refunded"
    over = POLICY.evaluate(order(total=2000), 1500, 1000, EVAL_NOW)
    assert (over.reason, over.amount) == ("exceeds_refundable", 1000)
    rest = POLICY.evaluate(order(total=2000), None, 1500, EVAL_NOW)
    assert (rest.action, rest.amount) == ("approve", 500)


def test_address_policy_by_status():
    p = AddressPolicy()
    assert p.evaluate({"status": "placed"}).allowed
    assert p.evaluate({"status": "packed"}).allowed
    assert p.evaluate({"status": "dispatched"}).reason == "already_dispatched"
    assert p.evaluate({"status": "delivered"}).reason == "already_dispatched"
    assert p.evaluate({"status": "cancelled"}).reason == "order_cancelled"
