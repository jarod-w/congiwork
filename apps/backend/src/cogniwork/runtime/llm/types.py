"""LLMClient 抽象。业务层不感知供应商（P0-03 §7）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: str
    content: str
    tool_call_id: str | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class ToolCallDelta:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class LLMResult:
    text: str
    tool_calls: list[ToolCallDelta] = field(default_factory=list)
    token_in: int = 0
    token_out: int = 0
    vendor: str = "stub"
    model: str = "stub-local"


class LLMClient(Protocol):
    vendor: str
    model: str

    def complete(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
        *,
        on_delta: Any | None = None,
    ) -> LLMResult: ...
