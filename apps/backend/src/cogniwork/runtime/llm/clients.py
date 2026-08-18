"""Anthropic + OpenAI 适配。tool-use / 流式差异在这里消化。"""

from __future__ import annotations

import json
from typing import Any

from cogniwork.core.errors import UpstreamError
from cogniwork.core.ids import new_id

from .types import ChatMessage, LLMResult, ToolCallDelta


class OpenAICompatClient:
    vendor = "openai"

    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        from openai import OpenAI

        self.model = model
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)

    def complete(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
        *,
        on_delta: Any | None = None,
    ) -> LLMResult:
        payload = [_openai_message(m) for m in messages]
        kwargs: dict[str, Any] = {"model": self.model, "messages": payload, "stream": False}
        if tools:
            kwargs["tools"] = tools
        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise UpstreamError("The language model did not respond.") from exc
        choice = response.choices[0].message
        text = choice.content or ""
        if on_delta and text:
            on_delta(text)
        calls: list[ToolCallDelta] = []
        for item in choice.tool_calls or []:
            try:
                args = json.loads(item.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCallDelta(item.id, item.function.name, args))
        usage = response.usage
        return LLMResult(
            text=text,
            tool_calls=calls,
            token_in=getattr(usage, "prompt_tokens", 0) or 0,
            token_out=getattr(usage, "completion_tokens", 0) or 0,
            vendor=self.vendor,
            model=self.model,
        )


class AnthropicClient:
    vendor = "anthropic"

    def __init__(self, api_key: str, model: str) -> None:
        import anthropic

        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key)

    def complete(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
        *,
        on_delta: Any | None = None,
    ) -> LLMResult:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        converted = _anthropic_messages(messages)
        anthropic_tools = [_anthropic_tool(t) for t in tools]
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": converted,
        }
        if system:
            kwargs["system"] = system
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools
        try:
            response = self._client.messages.create(**kwargs)
        except Exception as exc:
            raise UpstreamError("The language model did not respond.") from exc
        text_parts: list[str] = []
        calls: list[ToolCallDelta] = []
        for block in response.content:
            btype = getattr(block, "type", "")
            if btype == "text":
                text_parts.append(block.text)
            elif btype == "tool_use":
                calls.append(
                    ToolCallDelta(
                        getattr(block, "id", str(new_id())),
                        block.name,
                        dict(block.input or {}),
                    )
                )
        text = "".join(text_parts)
        if on_delta and text:
            on_delta(text)
        usage = response.usage
        return LLMResult(
            text=text,
            tool_calls=calls,
            token_in=getattr(usage, "input_tokens", 0) or 0,
            token_out=getattr(usage, "output_tokens", 0) or 0,
            vendor=self.vendor,
            model=self.model,
        )


def _openai_message(message: ChatMessage) -> dict[str, Any]:
    if message.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id or "",
            "content": message.content,
        }
    return {"role": message.role, "content": message.content}


def _anthropic_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    pending_tools: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            continue
        if message.role == "tool":
            pending_tools.append(
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id or "",
                    "content": message.content,
                }
            )
            continue
        if pending_tools:
            converted.append({"role": "user", "content": pending_tools})
            pending_tools = []
        converted.append({"role": message.role, "content": message.content})
    if pending_tools:
        converted.append({"role": "user", "content": pending_tools})
    if not converted:
        converted.append({"role": "user", "content": "Continue."})
    return converted


def _anthropic_tool(tool: dict[str, Any]) -> dict[str, Any]:
    fn = tool["function"]
    return {
        "name": fn["name"],
        "description": fn.get("description") or "",
        "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
    }
