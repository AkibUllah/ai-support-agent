from support_agent.config import PROJECT_ROOT
from support_agent.domain.db import Database
from support_agent.domain.repository import Repository
from support_agent.domain.seed import seed
from support_agent.evals.runner import EVAL_NOW
from support_agent.faq import FAQIndex


def test_seed_is_idempotent_and_totals_match_items():
    db = Database(":memory:")
    seed(db, EVAL_NOW)
    seed(db, EVAL_NOW)
    repo = Repository(db)
    assert len(repo.list_customers()) == 4
    order = repo.get_order("HO-10021")
    assert order["total"] == sum(i["quantity"] * i["unit_price"] for i in order["items"])
    assert order["shipment"]["events"][-1]["status"].startswith("Delivered")


def test_ticket_and_refund_ids_are_sequential():
    db = Database(":memory:")
    seed(db, EVAL_NOW)
    repo = Repository(db)
    assert (
        repo.create_ticket("C001", None, "other", "something happened", "low", EVAL_NOW)
        == "TK-0001"
    )
    assert repo.create_refund("HO-10021", 100, "approved", "r", EVAL_NOW) == "RF-0002"


def test_faq_search_english_and_bangla():
    faq = FAQIndex.load(PROJECT_ROOT / "data" / "faq.json")
    assert faq.search("cash on delivery limit")[0][0].id == "payment-methods"
    assert faq.search("রিফান্ড কীভাবে পাব")[0][0].id == "bn-refund"
    assert faq.search("motorbike") == []
