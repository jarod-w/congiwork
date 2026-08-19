"""MCP Executor. Receives calls that have already passed the consent gate."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from cogniwork.runtime.tools.spec import ToolResult, ToolSpec
from cogniwork.tools.catalog import ToolCatalog, load_catalog
from cogniwork.tools.http import HttpTransport
from cogniwork.tools.mcp import InProcessMcpClient
from cogniwork.tools.service import ToolService


class McpExecutor:
    def __init__(
        self,
        tools: ToolService,
        *,
        catalog: ToolCatalog | None = None,
        transport: HttpTransport | None = None,
    ) -> None:
        self._tools = tools
        self._catalog = catalog or load_catalog()
        self._client = InProcessMcpClient(self._catalog, transport or tools.transport)

    def invoke(
        self, spec: ToolSpec, arguments: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult:
        found = self._catalog.tool(spec.name)
        if found is None:
            return ToolResult(spec.name, False, f"Unknown MCP tool: {spec.name}")
        user_id = UUID(str(context["user_id"]))
        token = self._tools.token_for(user_id, found.provider)
        if not token:
            return ToolResult(
                spec.name,
                False,
                "This account is not connected. Connect it in Settings, or paste the "
                "content you want me to work with.",
                {"provider": found.provider},
            )
        return self._client.call(found.provider, found.mcp_name, arguments, token)
