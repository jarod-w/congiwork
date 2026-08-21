"""MCP Executor. Receives calls that have already passed the consent gate."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from cogniwork.core.config import Settings
from cogniwork.runtime.tools.spec import ToolResult, ToolSpec
from cogniwork.tools.catalog import ToolCatalog, load_catalog
from cogniwork.tools.http import HttpTransport
from cogniwork.tools.mcp import build_mcp_client
from cogniwork.tools.service import ToolService


class McpExecutor:
    def __init__(
        self,
        tools: ToolService,
        *,
        catalog: ToolCatalog | None = None,
        transport: HttpTransport | None = None,
        settings: Settings | None = None,
        client: Any | None = None,
    ) -> None:
        self._tools = tools
        self._catalog = catalog or load_catalog()
        # 传输形态从配置来（P0-05 §3）。写死 in-process 等于把「连接器崩溃
        # 只影响该用户该连接」这条隔离要求从实际路径上拿掉。
        self._client = client or build_mcp_client(
            settings or tools.settings,
            catalog=self._catalog,
            transport=transport or tools.transport,
        )

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
