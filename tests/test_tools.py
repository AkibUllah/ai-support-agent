from support_agent.tools import build_registry

REG = build_registry()


def test_every_tool_exposes_a_json_schema():
    schemas = {s["name"]: s for s in REG.schemas()}
    assert set(schemas) == {
        "lookup_order",
        "track_shipment",
        "list_recent_orders",
        "initiate_refund",
        "update_address",
        "create_ticket",
        "search_faq",
        "handoff_to_human",
    }
    refund = schemas["initiate_refund"]["input_schema"]
    assert refund["type"] == "object" and set(refund["required"]) == {"order_id", "reason"}
    assert refund["additionalProperties"] is False


def test_lookup_own_order(ctx):
    out = REG.call(ctx("C001"), "lookup_order", {"order_id": "ho-10021"})
    assert out.status == "ok"
    assert out.result["order_id"] == "HO-10021" and out.result["total_bdt"] == 2450


def test_other_customers_order_looks_missing_and_is_audited(ctx, service):
    c = ctx("C001")
    out = REG.call(c, "lookup_order", {"order_id": "HO-10041"})
    assert out.status == "error" and out.result["error"] == "order_not_found"
    assert out.guardrails == [
        {"guardrail": "ownership_check", "order_id": "HO-10041", "blocked": True}
    ]
    assert service.repo.audit_events("cross_customer_access")


def test_unknown_order_is_not_audited(ctx, service):
    out = REG.call(ctx("C001"), "track_shipment", {"order_id": "HO-99999"})
    assert out.result["error"] == "order_not_found"
    assert service.repo.audit_events("cross_customer_access") == []


def test_argument_validation_rejects_bad_ids_extra_fields_and_short_addresses(ctx):
    c = ctx("C001")
    assert REG.call(c, "lookup_order", {"order_id": "10021"}).status == "invalid_arguments"
    assert (
        REG.call(c, "lookup_order", {"order_id": "HO-10021", "customer_id": "C003"}).status
        == "invalid_arguments"
    )
    bad = REG.call(c, "update_address", {"order_id": "HO-10025", "new_address": "Dhaka"})
    assert bad.status == "invalid_arguments"
    assert bad.result["problems"][0]["field"] == "new_address"
    assert REG.call(c, "launch_rockets", {}).status == "unknown_tool"


def test_refund_auto_approval_writes_a_refund(ctx, service):
    out = REG.call(
        ctx("C001"), "initiate_refund", {"order_id": "HO-10021", "reason": "stopped working"}
    )
    assert out.result["status"] == "approved" and out.result["amount_bdt"] == 2450
    assert [r["status"] for r in service.repo.list_refunds("HO-10021")] == ["approved"]


def test_refund_above_limit_escalates_with_ticket_and_handoff(ctx, service):
    c = ctx("C001")
    out = REG.call(c, "initiate_refund", {"order_id": "HO-10022", "reason": "changed my mind"})
    assert out.result["status"] == "pending_review"
    ticket = service.repo.list_tickets()[0]
    assert ticket["priority"] == "high" and ticket["order_id"] == "HO-10022"
    assert c.handoff_reason and "12,500" in c.handoff_reason


def test_address_update_respects_dispatch_state(ctx, service):
    c = ctx("C001")
    ok = REG.call(
        c,
        "update_address",
        {"order_id": "HO-10025", "new_address": "House 9, Road 2, Banani, Dhaka"},
    )
    assert ok.result["status"] == "updated"
    assert (
        service.repo.get_order("HO-10025")["shipping_address"] == "House 9, Road 2, Banani, Dhaka"
    )
    denied = REG.call(
        c,
        "update_address",
        {"order_id": "HO-10024", "new_address": "House 9, Road 2, Banani, Dhaka"},
    )
    assert denied.result["reason"] == "already_dispatched"


def test_track_list_ticket_and_faq(ctx):
    c = ctx("C001")
    assert REG.call(c, "track_shipment", {"order_id": "HO-10025"}).result["shipment"] is None
    track = REG.call(c, "track_shipment", {"order_id": "HO-10024"}).result
    assert track["courier"] == "Padma Courier" and track["latest_event"]["status"].startswith(
        "Out for"
    )
    orders = REG.call(c, "list_recent_orders", {"limit": 2}).result["orders"]
    assert [o["order_id"] for o in orders] == ["HO-10025", "HO-10024"]
    ticket = REG.call(
        c,
        "create_ticket",
        {"category": "product", "summary": "Kettle lid is loose", "order_id": "HO-10024"},
    ).result
    assert ticket["ticket_id"] == "TK-0001"
    faq = REG.call(c, "search_faq", {"query": "ডেলিভারিতে কত দিন লাগে"}).result["results"]
    assert faq[0]["id"] == "bn-delivery"
