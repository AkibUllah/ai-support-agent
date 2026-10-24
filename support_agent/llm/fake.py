"""Deterministic, offline "policy model" that drives the agent without an API key.

It plays the role an LLM plays in production: read the conversation, pick a tool and
arguments, then phrase a reply from the tool result. Intent detection is keyword-based
(English + Bangla) with conversational memory for the last order number and the last
unfinished request. It is intentionally *not* policy-aware: it will happily ask for a
৳12,500 refund or another customer's order, so the evals prove that the guardrails and
policy engine, not the model, keep the shop safe.
"""

from __future__ import annotations

import json
import re
from typing import Any

from support_agent.clock import DHAKA, parse_ts
from support_agent.llm.base import AssistantMessage, ToolCall
from support_agent.text import is_bangla

ORDER_RE = re.compile(r"\bHO[-\s]?(\d{5})\b", re.I)
AMOUNT_RE = re.compile(
    r"(?:৳|\btk\.?|\bbdt|\btaka)\s*([\d০-৯][\d০-৯,]*)|([\d০-৯][\d০-৯,]*)\s*(?:৳|tk\b|taka\b|bdt\b|টাকা)",
    re.I,
)
# "address of HO-10025 to ...", "address for HO-10034 is ...", "new address: ...", "ঠিকানা: ..."
# (order numbers are blanked out before matching).
ADDRESS_RE = re.compile(
    r"(?:address(?:\s+(?:of|for))?\s*(?:to|is|:|-)|ঠিকানা\s*(?:হলো|:|ঃ))\s*(.+)$", re.I | re.S
)
GENERAL_QUESTION_RE = re.compile(
    r"^\s*(can|could|how|what|when|is|are|do|does|which)\b|\bpolic(y|ies)\b|নিয়ম|কীভাবে|কিভাবে", re.I
)
BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

INTENTS: list[tuple[str, re.Pattern[str]]] = [
    (
        "human",
        re.compile(
            r"\b(human|real person|representative|manager|supervisor|live agent|talk to (a |an )?(person|agent|someone))\b|মানুষের সাথে|প্রতিনিধি",
            re.I,
        ),
    ),
    ("cancel", re.compile(r"\bcancel|বাতিল", re.I)),
    (
        "complaint",
        re.compile(r"damaged|broken|wrong item|missing|defective|cracked|not working|ভাঙা|নষ্ট", re.I),
    ),
    ("refund", re.compile(r"refund|money back|\breturn\b|ফেরত|রিফান্ড", re.I)),
    ("address", re.compile(r"\baddress\b|ঠিকানা", re.I)),
    (
        "track",
        re.compile(
            r"\btrack|where is|where's|when will|arriv|delivery status|shipment|courier|rider|কোথায়|কবে পাব|ট্র্যাক",
            re.I,
        ),
    ),
    (
        "orders",
        re.compile(
            r"my orders|recent orders|order history|past orders|list (my |all )?orders|আমার অর্ডারগুলো|সাম্প্রতিক অর্ডার",
            re.I,
        ),
    ),
    ("status", re.compile(r"\bstatus\b|details|what('s| is) in|অবস্থা|স্ট্যাটাস", re.I)),
    ("thanks", re.compile(r"^\s*(thanks|thank you|ok thanks|ধন্যবাদ)\b", re.I)),
    (
        "greeting",
        re.compile(
            r"^\s*(hi|hello|hey|salam|assalamu ?alaikum|good (morning|evening)|হ্যালো|আসসালামু)\b", re.I
        ),
    ),
]
NEEDS_ORDER = {"cancel", "complaint", "refund", "address", "track", "status"}

T = {
    "en": {
        "greeting": "Hello{name}! I can track orders, check order details, process refunds, update a delivery address or answer questions about Haat Online. How can I help?",
        "thanks": "You're welcome! Anything else I can help with?",
        "ask_order": "Which order do you mean? Please share the order number (for example HO-10021).",
        "pick_order": "Here are your recent orders:\n{orders}\nWhich one do you mean?",
        "orders": "Here are your recent orders:\n{orders}",
        "no_orders": "I couldn't find any orders on your account.",
        "not_found": "I couldn't find order {order_id} on your account. Please check the number, or ask me to list your recent orders.",
        "status": "Order {order_id} is {status}. Total ৳{total:,}, paid by {payment}. Items: {items}.",
        "status_delivered": "Order {order_id} was delivered on {date}. Total ৳{total:,}, paid by {payment}. Items: {items}.",
        "track": "Order {order_id} is with {courier} (tracking {tracking}). Latest update: {event}.{eta}",
        "track_delivered": "Order {order_id} was delivered by {courier} (tracking {tracking}). Latest update: {event}.",
        "track_none": "Order {order_id} is {status} and has not been handed to a courier yet.",
        "track_cancelled": "Order {order_id} was cancelled, so there is nothing to track.",
        "refund_approved": "Done: refund {refund_id} of ৳{amount:,} for {order_id} is approved. {timeline}",
        "refund_review": "Your refund request of ৳{amount:,} for {order_id} needs a quick review by our team because it is above ৳5,000 (ticket {ticket_id}). A team member will take over this chat and reply within 1 working day.",
        "refund_denied": "I can't refund {order_id}: {message}",
        "address_updated": "The delivery address for {order_id} is now: {address}.",
        "address_denied": "I can't change the address for {order_id}: {message}",
        "ask_address": "What is the new delivery address for {order_id}? Please include house, road, area and city.",
        "bad_address": "That address looks incomplete. Please share the full address with house, road, area and city.",
        "ticket": "I've opened ticket {ticket_id} ({category}) for you. Our team will follow up by phone or email.",
        "handoff": "I'm handing this conversation to a human colleague (ticket {ticket_id}). They will reply here shortly.",
        "faq": "{answer}",
        "faq_none": "I don't have an answer for that. I can open a ticket so a colleague can help.",
        "invalid": "I couldn't do that because some details were missing or invalid: {problems}.",
        "fallback": "I can help with order status, tracking, refunds, address changes and questions about delivery, payments and returns. What would you like to do?",
    },
    "bn": {
        "greeting": "আসসালামু আলাইকুম{name}! আমি অর্ডার ট্র্যাক, রিফান্ড, ঠিকানা পরিবর্তন এবং হাট অনলাইনের যেকোনো প্রশ্নে সাহায্য করতে পারি।",
        "thanks": "আপনাকেও ধন্যবাদ! আর কিছু জানতে চান?",
        "ask_order": "কোন অর্ডারের কথা বলছেন? অর্ডার নম্বরটি দিন (যেমন HO-10021)।",
        "pick_order": "আপনার সাম্প্রতিক অর্ডারগুলো:\n{orders}\nকোনটির কথা বলছেন?",
        "orders": "আপনার সাম্প্রতিক অর্ডারগুলো:\n{orders}",
        "no_orders": "আপনার অ্যাকাউন্টে কোনো অর্ডার পাওয়া যায়নি।",
        "not_found": "আপনার অ্যাকাউন্টে {order_id} নম্বরের কোনো অর্ডার পাওয়া যায়নি।",
        "status": "অর্ডার {order_id} এখন {status} অবস্থায় আছে। মোট ৳{total:,}।",
        "status_delivered": "অর্ডার {order_id} {date} তারিখে ডেলিভারি হয়েছে। মোট ৳{total:,}।",
        "track": "অর্ডার {order_id} এখন {courier}-এর কাছে (ট্র্যাকিং {tracking})। সর্বশেষ আপডেট: {event}।{eta}",
        "track_delivered": "অর্ডার {order_id} {courier}-এর মাধ্যমে ডেলিভারি হয়েছে (ট্র্যাকিং {tracking})।",
        "track_none": "অর্ডার {order_id} এখনো কুরিয়ারে দেওয়া হয়নি ({status})।",
        "track_cancelled": "অর্ডার {order_id} বাতিল করা হয়েছে।",
        "refund_approved": "রিফান্ড {refund_id} অনুমোদিত হয়েছে: {order_id} অর্ডারের জন্য ৳{amount:,}। {timeline}",
        "refund_review": "{order_id} অর্ডারের ৳{amount:,} রিফান্ডটি ৫,০০০ টাকার বেশি হওয়ায় আমাদের টিম যাচাই করবে (টিকিট {ticket_id})। একজন প্রতিনিধি ১ কার্যদিবসের মধ্যে উত্তর দেবেন।",
        "refund_denied": "{order_id} অর্ডারের রিফান্ড দেওয়া সম্ভব নয়: {message}",
        "address_updated": "{order_id} অর্ডারের নতুন ঠিকানা: {address}।",
        "address_denied": "{order_id} অর্ডারের ঠিকানা পরিবর্তন করা সম্ভব নয়: {message}",
        "ask_address": "{order_id} অর্ডারের নতুন ঠিকানা লিখুন (বাড়ি, রোড, এলাকা ও শহর)।",
        "bad_address": "ঠিকানাটি অসম্পূর্ণ মনে হচ্ছে। বাড়ি, রোড, এলাকা ও শহরসহ পুরো ঠিকানা দিন।",
        "ticket": "আপনার জন্য টিকিট {ticket_id} খোলা হয়েছে। আমাদের টিম যোগাযোগ করবে।",
        "handoff": "আমি কথোপকথনটি একজন প্রতিনিধির কাছে পাঠাচ্ছি (টিকিট {ticket_id})।",
        "faq": "{answer}",
        "faq_none": "এ বিষয়ে আমার কাছে তথ্য নেই। চাইলে একটি টিকিট খুলে দিতে পারি।",
        "invalid": "কিছু তথ্য অসম্পূর্ণ বা ভুল ছিল: {problems}।",
        "fallback": "আমি অর্ডারের অবস্থা, ট্র্যাকিং, রিফান্ড, ঠিকানা পরিবর্তন ও ডেলিভারি-পেমেন্ট বিষয়ক প্রশ্নে সাহায্য করতে পারি।",
    },
}

TIMELINE = {
    "bkash": "It reaches your bKash account within 3 working days.",
    "nagad": "It reaches your Nagad account within 3 working days.",
    "card": "It reaches your card within 7-10 working days.",
    "cod": "As this was cash on delivery, our team will call you for a bKash number to send it to.",
}
TIMELINE_BN = {
    "bkash": "৩ কার্যদিবসের মধ্যে বিকাশে টাকা পৌঁছে যাবে।",
    "nagad": "৩ কার্যদিবসের মধ্যে নগদে টাকা পৌঁছে যাবে।",
    "card": "৭-১০ কার্যদিবসের মধ্যে কার্ডে টাকা পৌঁছে যাবে।",
    "cod": "ক্যাশ অন ডেলিভারি অর্ডার হওয়ায় আমাদের টিম বিকাশ নম্বরের জন্য কল করবে।",
}


def detect_intent(text: str) -> str | None:
    for name, pattern in INTENTS:
        if pattern.search(text):
            return name
    if "?" in text or re.search(
        r"^\s*(how|what|when|can|do|does|is|which)\b|কি|কী|কত|কীভাবে|কেমন", text, re.I
    ):
        return "faq"
    return None


def find_order_id(text: str) -> str | None:
    m = ORDER_RE.search(text)
    return f"HO-{m.group(1)}" if m else None


def find_amount(text: str) -> int | None:
    m = AMOUNT_RE.search(ORDER_RE.sub(" ", text))
    if not m:
        return None
    raw = (m.group(1) or m.group(2)).translate(BN_DIGITS).replace(",", "")
    return int(raw) if raw.isdigit() and int(raw) > 0 else None


def find_address(text: str) -> str | None:
    m = ADDRESS_RE.search(ORDER_RE.sub(" ", text))
    return " ".join(m.group(1).split()).strip(" .") if m else None


def _fmt_date(ts: str | None) -> str:
    return ts[:10] if ts else "unknown date"


class ScriptedPolicyModel:
    name = "scripted-policy"

    def __init__(self) -> None:
        self.customer_name = ""

    # -- conversation helpers ------------------------------------------------------
    @staticmethod
    def _user_texts(messages: list[dict[str, Any]]) -> list[str]:
        return [m["content"] for m in messages if m["role"] == "user"]

    @staticmethod
    def _last_order_id(messages: list[dict[str, Any]]) -> str | None:
        for m in reversed(messages):
            if m["role"] == "user":
                found = find_order_id(m["content"])
                if found:
                    return found
            if m["role"] == "assistant":
                for tc in reversed(m.get("tool_calls", [])):
                    oid = tc["arguments"].get("order_id")
                    if isinstance(oid, str):
                        return oid.upper()
        return None

    # -- protocol ------------------------------------------------------------------
    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AssistantMessage:
        m = re.search(r"talking to (.+?) \(customer", system)
        self.customer_name = m.group(1) if m else ""
        if messages and messages[-1]["role"] == "tool":
            return self._reply_to_tool(messages)
        return self._plan(messages)

    def _call(self, n: int, name: str, **arguments: Any) -> AssistantMessage:
        args = {k: v for k, v in arguments.items() if v is not None}
        return AssistantMessage("", [ToolCall(f"call_{n}", name, args)])

    def _plan(self, messages: list[dict[str, Any]]) -> AssistantMessage:
        users = self._user_texts(messages)
        text = users[-1] if users else ""
        lang = "bn" if is_bangla(text) else "en"
        n = sum(len(m.get("tool_calls", [])) for m in messages if m["role"] == "assistant") + 1
        intent = detect_intent(text)
        order_id = find_order_id(text)

        # Resume an unfinished request: "refund please" ... "HO-10021", or an address
        # given in reply to "what is the new address?".
        if intent in (None, "faq") and len(users) > 1:
            previous = next(
                (detect_intent(u) for u in reversed(users[:-1]) if detect_intent(u) in NEEDS_ORDER),
                None,
            )
            if previous and (order_id or previous == "address"):
                intent = previous
        if intent in (None, "status") and order_id:
            intent = "status"
        # "What is your return policy?" / "Can I change my address?" are help-centre
        # questions, not requests about a specific order.
        if (
            intent in NEEDS_ORDER
            and not order_id
            and GENERAL_QUESTION_RE.search(text)
            and not self._last_order_id(messages[:-1])
        ):
            intent = "faq"
        if intent in NEEDS_ORDER and not order_id:
            order_id = self._last_order_id(messages[:-1])

        if intent == "greeting":
            name = f", {self.customer_name.split()[0]}" if self.customer_name else ""
            return AssistantMessage(T[lang]["greeting"].format(name=name))
        if intent == "thanks":
            return AssistantMessage(T[lang]["thanks"])
        if intent == "human":
            return self._call(n, "handoff_to_human", reason=text[:300])
        if intent == "orders":
            return self._call(n, "list_recent_orders", limit=5)
        if intent == "faq" or intent is None:
            if intent is None and not text.strip():
                return AssistantMessage(T[lang]["fallback"])
            return self._call(n, "search_faq", query=text[:200])
        if intent in NEEDS_ORDER and not order_id:
            return self._call(n, "list_recent_orders", limit=5)

        if intent == "status":
            return self._call(n, "lookup_order", order_id=order_id)
        if intent == "track":
            return self._call(n, "track_shipment", order_id=order_id)
        if intent == "refund":
            return self._call(
                n, "initiate_refund", order_id=order_id, reason=text[:300], amount=find_amount(text)
            )
        if intent == "address":
            address = find_address(text)
            if address is None and detect_intent(text) is None:
                address = " ".join(ORDER_RE.sub(" ", text).split())  # whole reply is the address
            if not address:
                return AssistantMessage(T[lang]["ask_address"].format(order_id=order_id))
            return self._call(n, "update_address", order_id=order_id, new_address=address)
        if intent == "cancel":
            return self._call(
                n,
                "create_ticket",
                category="cancellation",
                order_id=order_id,
                summary=f"Customer asked to cancel {order_id}: {text[:200]}",
            )
        if intent == "complaint":
            return self._call(
                n,
                "create_ticket",
                category="product",
                order_id=order_id,
                priority="high",
                summary=f"Problem with {order_id}: {text[:200]}",
            )
        return AssistantMessage(T[lang]["fallback"])  # pragma: no cover - all intents handled

    def _reply_to_tool(self, messages: list[dict[str, Any]]) -> AssistantMessage:
        users = self._user_texts(messages)
        lang = "bn" if users and is_bangla(users[-1]) else "en"
        t = T[lang]
        tool_msg = messages[-1]
        name = tool_msg["name"]
        result = json.loads(tool_msg["content"])
        call = next(
            tc
            for m in reversed(messages)
            if m["role"] == "assistant"
            for tc in m.get("tool_calls", [])
            if tc["id"] == tool_msg["tool_call_id"]
        )
        args = call["arguments"]

        if result.get("error") == "order_not_found":
            return AssistantMessage(t["not_found"].format(order_id=args.get("order_id", "")))
        if result.get("error") == "invalid_arguments":
            fields = {p["field"] for p in result["problems"]}
            if name == "update_address" and "new_address" in fields:
                return AssistantMessage(t["bad_address"])
            problems = "; ".join(f"{p['field']}: {p['problem']}" for p in result["problems"])
            return AssistantMessage(t["invalid"].format(problems=problems))
        if "error" in result:
            return AssistantMessage(
                t["invalid"].format(problems=result.get("message", result["error"]))
            )

        if name == "list_recent_orders":
            orders = result["orders"]
            if not orders:
                return AssistantMessage(t["no_orders"])
            listing = "\n".join(
                f"- {o['order_id']}: {o['status']}, ৳{o['total_bdt']:,}" for o in orders
            )
            pending = detect_intent(users[-1]) if users else None
            key = "pick_order" if pending in NEEDS_ORDER else "orders"
            return AssistantMessage(t[key].format(orders=listing))
        if name == "lookup_order":
            items = ", ".join(f"{i['product']} x{i['quantity']}" for i in result["items"])
            key = "status_delivered" if result["status"] == "delivered" else "status"
            return AssistantMessage(
                t[key].format(
                    order_id=result["order_id"],
                    status=result["status"],
                    total=result["total_bdt"],
                    payment=result["payment_method"],
                    items=items,
                    date=_fmt_date(result["delivered_at"]),
                )
            )
        if name == "track_shipment":
            if result.get("status") == "cancelled":
                return AssistantMessage(t["track_cancelled"].format(order_id=result["order_id"]))
            if result.get("shipment", True) is None:
                return AssistantMessage(
                    t["track_none"].format(order_id=result["order_id"], status=result["status"])
                )
            event = (result.get("latest_event") or {}).get("status", "no updates yet")
            key = "track_delivered" if result["status"] == "delivered" else "track"
            eta = ""
            if result.get("eta"):
                local = parse_ts(result["eta"]).astimezone(DHAKA)
                eta = f" Expected by {local:%d %b, %I:%M %p} (Dhaka time)."
            return AssistantMessage(
                t[key].format(
                    order_id=result["order_id"],
                    courier=result["courier"],
                    tracking=result["tracking_no"],
                    event=event,
                    eta=eta,
                )
            )
        if name == "initiate_refund":
            if result["status"] == "approved":
                timeline = (TIMELINE_BN if lang == "bn" else TIMELINE).get(
                    result["payment_method"], ""
                )
                return AssistantMessage(
                    t["refund_approved"].format(
                        refund_id=result["refund_id"],
                        amount=result["amount_bdt"],
                        order_id=result["order_id"],
                        timeline=timeline,
                    )
                )
            if result["status"] == "pending_review":
                return AssistantMessage(
                    t["refund_review"].format(
                        amount=result["amount_bdt"],
                        order_id=result["order_id"],
                        ticket_id=result["ticket_id"],
                    )
                )
            return AssistantMessage(
                t["refund_denied"].format(order_id=result["order_id"], message=result["message"])
            )
        if name == "update_address":
            if result["status"] == "updated":
                return AssistantMessage(
                    t["address_updated"].format(
                        order_id=result["order_id"], address=result["new_address"]
                    )
                )
            return AssistantMessage(
                t["address_denied"].format(order_id=result["order_id"], message=result["message"])
            )
        if name == "create_ticket":
            return AssistantMessage(
                t["ticket"].format(ticket_id=result["ticket_id"], category=result["category"])
            )
        if name == "handoff_to_human":
            return AssistantMessage(t["handoff"].format(ticket_id=result["ticket_id"]))
        if name == "search_faq":
            hits = result["results"]
            if not hits or hits[0]["score"] < 1.0:
                return AssistantMessage(t["faq_none"])
            return AssistantMessage(t["faq"].format(answer=hits[0]["answer"]))
        return AssistantMessage(t["fallback"])
