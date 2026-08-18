"""ToolSpec —— Runtime 只认识这一层，不认识 MCP / 桌面 / 浏览器（P0-03 §5）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from cogniwork.consent.models import Risk

Provider = Literal["mcp", "desktop", "browser", "builtin"]
PreviewRenderer = Literal["email", "table", "diff", "text"]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    provider: Provider
    description: str
    input_schema: dict[str, Any]
    scope_key: str | None
    risk: Risk
    preview_renderer: PreviewRenderer | None = None
    timeout_s: int = 60
    retryable: bool = True


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    call_id: str = ""


@dataclass(slots=True)
class ToolResult:
    name: str
    ok: bool
    content: str
    data: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False
    needs_approval: bool = False


class Executor(Protocol):
    """执行器只接收「已经放行的调用」。内部不得做权限判断。"""

    def invoke(
        self, spec: ToolSpec, arguments: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult: ...
