"""OpenAI-compatible ``/chat/completions`` adapter with function calling."""

from __future__ import annotations

import json
from typing import Any

import httpx

from support_agent.llm.base import AssistantMessage, LLMError, ToolCall


def to_openai(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for m in messages:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": m.get("content") or None}
            if m.get("tool_calls"):
                msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                        },
                    }
                    for tc in m["tool_calls"]
                ]
            out.append(msg)
        elif m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
    return out


def to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


def from_openai(body: dict[str, Any]) -> AssistantMessage:
    try:
        msg = body["choices"][0]["message"]
        calls = []
        for tc in msg.get("tool_calls") or []:
            raw = tc["function"].get("arguments") or "{}"
            try:
                args = json.loads(raw)
            except json.JSONDecodeError:
                # Keep the call so argument validation reports it back to the model.
                args = {"__unparseable_arguments__": raw}
            calls.append(
                ToolCall(tc["id"], tc["function"]["name"], args if isinstance(args, dict) else {})
            )
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("malformed chat completion response") from exc
    return AssistantMessage((msg.get("content") or "").strip(), calls)


class OpenAICompatibleLLM:
    name = "openai"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        *,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self._client = client or httpx.Client(timeout=timeout)

    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AssistantMessage:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": to_openai(system, messages),
            "tools": to_openai_tools(tools),
        }
        try:
            resp = self._client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"openai-compatible request failed: {exc}") from exc
        return from_openai(resp.json())
