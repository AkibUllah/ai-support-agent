"""Anthropic Messages API adapter with tool use (plain httpx, no SDK)."""

from __future__ import annotations

from typing import Any

import httpx

from support_agent.llm.base import AssistantMessage, LLMError, ToolCall


def to_anthropic(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Internal messages -> Anthropic ``messages``. Consecutive tool results are merged
    into one user turn of ``tool_result`` blocks, as the API requires."""
    out: list[dict[str, Any]] = []
    for m in messages:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            blocks: list[dict[str, Any]] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m.get("tool_calls", []):
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc["arguments"],
                    }
                )
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
        elif m["role"] == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": m["tool_call_id"],
                "content": m["content"],
            }
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return out


def from_anthropic(body: dict[str, Any]) -> AssistantMessage:
    try:
        blocks = body["content"]
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        calls = [
            ToolCall(b["id"], b["name"], b.get("input") or {})
            for b in blocks
            if b.get("type") == "tool_use"
        ]
    except (KeyError, TypeError) as exc:
        raise LLMError("malformed Anthropic response") from exc
    return AssistantMessage(text.strip(), calls)


class AnthropicLLM:
    name = "anthropic"
    api_version = "2023-06-01"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        *,
        timeout: float = 30.0,
        max_tokens: int = 1024,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.max_tokens = max_tokens
        self._client = client or httpx.Client(timeout=timeout)

    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AssistantMessage:
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": to_anthropic(messages),
            "tools": tools,
        }
        try:
            resp = self._client.post(
                f"{self.base_url}/v1/messages",
                json=payload,
                headers={"x-api-key": self.api_key, "anthropic-version": self.api_version},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"anthropic request failed: {exc}") from exc
        return from_anthropic(resp.json())
