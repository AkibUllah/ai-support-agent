import json

import httpx
import pytest

from support_agent.llm.anthropic import AnthropicLLM, from_anthropic, to_anthropic
from support_agent.llm.base import LLMError
from support_agent.llm.openai_compat import OpenAICompatibleLLM, from_openai, to_openai

HISTORY = [
    {"role": "user", "content": "Where is HO-10024 and HO-10021?"},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": "t1", "name": "track_shipment", "arguments": {"order_id": "HO-10024"}},
            {"id": "t2", "name": "track_shipment", "arguments": {"order_id": "HO-10021"}},
        ],
    },
    {
        "role": "tool",
        "tool_call_id": "t1",
        "name": "track_shipment",
        "content": '{"status":"dispatched"}',
    },
    {
        "role": "tool",
        "tool_call_id": "t2",
        "name": "track_shipment",
        "content": '{"status":"delivered"}',
    },
]
TOOLS = [{"name": "track_shipment", "description": "d", "input_schema": {"type": "object"}}]


def test_anthropic_translation_merges_tool_results_into_one_user_turn():
    msgs = to_anthropic(HISTORY)
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert [b["type"] for b in msgs[1]["content"]] == ["tool_use", "tool_use"]
    assert [b["tool_use_id"] for b in msgs[2]["content"]] == ["t1", "t2"]


def test_anthropic_response_parsing():
    out = from_anthropic(
        {
            "content": [
                {"type": "text", "text": "Let me check."},
                {
                    "type": "tool_use",
                    "id": "tu_1",
                    "name": "lookup_order",
                    "input": {"order_id": "HO-10021"},
                },
            ],
            "stop_reason": "tool_use",
        }
    )
    assert out.text == "Let me check."
    assert out.tool_calls[0].name == "lookup_order" and out.tool_calls[0].arguments == {
        "order_id": "HO-10021"
    }
    with pytest.raises(LLMError):
        from_anthropic({"oops": True})


def test_openai_translation_and_unparseable_arguments():
    msgs = to_openai("sys", HISTORY)
    assert msgs[0] == {"role": "system", "content": "sys"}
    assert json.loads(msgs[2]["tool_calls"][0]["function"]["arguments"]) == {"order_id": "HO-10024"}
    assert msgs[3] == {"role": "tool", "tool_call_id": "t1", "content": '{"status":"dispatched"}'}
    out = from_openai(
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {"name": "lookup_order", "arguments": "{not json"},
                            },
                        ],
                    }
                }
            ]
        }
    )
    assert out.tool_calls[0].arguments == {"__unparseable_arguments__": "{not json"}


def _client(captured, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if status != 200:
            return httpx.Response(status, json={"error": "rate limited"})
        if request.url.path == "/v1/messages":
            return httpx.Response(200, json={"content": [{"type": "text", "text": "hi"}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_providers_send_expected_requests():
    captured: list[httpx.Request] = []
    a = AnthropicLLM("https://anthropic.test", "model-a", "key-a", client=_client(captured))
    assert a.complete("sys", HISTORY, TOOLS).text == "hi"
    o = OpenAICompatibleLLM("https://oa.test/v1", "model-o", "key-o", client=_client(captured))
    assert o.complete("sys", HISTORY, TOOLS).text == "hello"
    req_a, req_o = captured
    body_a = json.loads(req_a.content)
    assert (
        req_a.headers["x-api-key"] == "key-a" and req_a.headers["anthropic-version"] == "2023-06-01"
    )
    assert body_a["system"] == "sys" and body_a["tools"] == TOOLS
    body_o = json.loads(req_o.content)
    assert req_o.headers["authorization"] == "Bearer key-o"
    assert body_o["tools"][0]["function"]["parameters"] == {"type": "object"}


def test_provider_http_errors_become_llm_errors():
    with pytest.raises(LLMError):
        AnthropicLLM("https://anthropic.test", "m", "k", client=_client([], status=429)).complete(
            "s", [], []
        )
    with pytest.raises(LLMError):
        OpenAICompatibleLLM("https://oa.test", "m", client=_client([], status=500)).complete(
            "s", [], []
        )
