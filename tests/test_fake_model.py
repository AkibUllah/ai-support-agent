import pytest

from support_agent.llm.fake import (
    ScriptedPolicyModel,
    detect_intent,
    find_address,
    find_amount,
    find_order_id,
)


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("Where is my order?", "track"),
        ("refund HO-10021", "refund"),
        ("I want to talk to a human", "human"),
        ("Please cancel HO-10025", "cancel"),
        ("It arrived broken", "complaint"),
        ("show my recent orders", "orders"),
        ("hello", "greeting"),
        ("আমার অর্ডার কোথায়?", "track"),
        ("রিফান্ড চাই", "refund"),
        ("Do you deliver to Sylhet?", "faq"),
    ],
)
def test_intent_detection(text, intent):
    assert detect_intent(text) == intent


def test_order_amount_and_address_extraction():
    assert find_order_id("about ho 10021 please") == "HO-10021"
    assert find_amount("refund ৳1,200 for HO-10021") == 1200
    assert find_amount("HO-10031 এর ৫০০ টাকা ফেরত") == 500
    assert find_amount("refund HO-10021") is None
    assert (
        find_address("change the address of HO-10025 to House 9, Road 2, Banani")
        == "House 9, Road 2, Banani"
    )
    assert find_address("I need to change the delivery address for HO-10034") is None
    assert find_address("new address: Flat 3C, Gulshan 2, Dhaka") == "Flat 3C, Gulshan 2, Dhaka"


def test_general_questions_go_to_the_help_centre():
    model = ScriptedPolicyModel()
    msg = model.complete(
        "You are talking to Rahim Uddin (customer C001)",
        [{"role": "user", "content": "What is your return policy?"}],
        [],
    )
    assert msg.tool_calls[0].name == "search_faq"


def test_greeting_uses_the_customer_name_from_the_system_prompt():
    model = ScriptedPolicyModel()
    msg = model.complete(
        "You are talking to Nusrat Jahan (customer C002)", [{"role": "user", "content": "hi"}], []
    )
    assert msg.tool_calls == [] and "Nusrat" in msg.text
