"""MCP JSON-RPC 2.0 subset: initialize / tools/list / tools/call (P0-05 M1).

Two transports, and the difference is not cosmetic (P0-05 §3):

- ``stdio`` runs the connector in its own process. A connector that segfaults
  or hangs takes down one call, not the API. The token goes in via the child's
  environment, so two users' credentials never share a process. This is the
  production default.
- ``inprocess`` calls the adapter directly. It exists so tests can inject a
  transport and assert on the calls it recorded; a subprocess would not share
  that object. Selected with ``COGNIWORK_MCP_TRANSPORT=inprocess``.

streamable-http (remote third-party MCP servers) is not implemented — all four
Phase 1 connectors are self-hosted, so nothing consumes it. Registered as
deviation 11 in docs/design/README.md rather than left to look supported.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from typing import Any

from cogniwork.core.config import Settings, get_settings
from cogniwork.runtime.tools.spec import ToolResult
from cogniwork.tools.catalog import ToolCatalog, load_catalog
from cogniwork.tools.http import HttpTransport
from cogniwork.tools.providers import invoke_provider
from cogniwork.tools.vault import redact_obj

logger = logging.getLogger("cogniwork.tools.mcp")


def handle_rpc(
    request: dict[str, Any],
    *,
    provider: str,
    token: str,
    catalog: ToolCatalog,
    transport: HttpTransport,
) -> dict[str, Any]:
    req_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}
    if method == "initialize":
        return _ok(req_id, {"protocolVersion": "2024-11-05", "serverInfo": {"name": provider}})
    if method == "tools/list":
        spec = catalog.provider(provider)
        tools = [
            {
                "name": tool.mcp_name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            }
            for tool in spec.tools
        ]
        return _ok(req_id, {"tools": tools})
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = dict(params.get("arguments") or {})
        result = invoke_provider(provider, name, arguments, token, transport)
        return _ok(
            req_id,
            {
                "ok": result.ok,
                "content": result.content,
                "data": redact_obj(result.data),
            },
        )
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"},
    }


def _ok(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


class InProcessMcpClient:
    def __init__(self, catalog: ToolCatalog | None = None, transport: HttpTransport | None = None):
        self.catalog = catalog or load_catalog()
        self.transport = transport or HttpTransport()

    def call(
        self, provider: str, mcp_name: str, arguments: dict[str, Any], token: str
    ) -> ToolResult:
        rpc = handle_rpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": mcp_name, "arguments": arguments},
            },
            provider=provider,
            token=token,
            catalog=self.catalog,
            transport=self.transport,
        )
        if "error" in rpc:
            return ToolResult(mcp_name, False, str(rpc["error"]))
        payload = rpc.get("result") or {}
        return ToolResult(
            f"{provider}.{mcp_name}",
            bool(payload.get("ok")),
            str(payload.get("content") or ""),
            dict(payload.get("data") or {}),
        )


class StdioMcpClient:
    """One connector process per call.

    A long-lived pooled process would be cheaper, but the token is injected
    through the child's environment (P0-05 §3), and a shared process would mean
    a shared credential. Isolation wins: the spawn cost is small next to the
    upstream HTTP round trip these tools make anyway.
    """

    def __init__(self, *, timeout_s: int = 45) -> None:
        self.timeout_s = timeout_s

    def call(
        self, provider: str, mcp_name: str, arguments: dict[str, Any], token: str
    ) -> ToolResult:
        request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": mcp_name, "arguments": arguments},
            }
        )
        try:
            proc = subprocess.run(  # noqa: S603
                [sys.executable, "-m", "cogniwork.tools.mcp_server", "--provider", provider],
                input=request + "\n",
                capture_output=True,
                text=True,
                env=_child_env(token),
                check=False,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired:
            # 超时算一次失败，不重试也不猜结果 —— 重试的判断在 resilience 里，
            # 它知道这次调用是不是 irreversible（P0-05 §6）。
            return ToolResult(
                f"{provider}.{mcp_name}",
                False,
                "The connector did not answer in time.",
                {"provider": provider, "timeout": True},
            )
        if proc.returncode != 0:
            # stderr 不进日志正文：连接器崩溃时的 traceback 可能带上参数
            # （硬约束 9 / 8）。只记 returncode。
            logger.warning("mcp connector %s exited with %s", provider, proc.returncode)
            return ToolResult(
                f"{provider}.{mcp_name}",
                False,
                "The connector process failed. Other connectors still work.",
                {"provider": provider, "exit_code": proc.returncode},
            )
        line = (proc.stdout or "").strip().splitlines()[-1] if (proc.stdout or "").strip() else ""
        if not line:
            return ToolResult(
                f"{provider}.{mcp_name}",
                False,
                "The connector returned nothing.",
                {"provider": provider},
            )
        try:
            rpc = json.loads(line)
        except json.JSONDecodeError:
            return ToolResult(
                f"{provider}.{mcp_name}",
                False,
                "The connector returned a malformed response.",
                {"provider": provider},
            )
        if "error" in rpc:
            return ToolResult(f"{provider}.{mcp_name}", False, str(rpc["error"]))
        payload = rpc.get("result") or {}
        return ToolResult(
            f"{provider}.{mcp_name}",
            bool(payload.get("ok")),
            str(payload.get("content") or ""),
            dict(payload.get("data") or {}),
        )


def build_mcp_client(
    settings: Settings | None = None,
    *,
    catalog: ToolCatalog | None = None,
    transport: HttpTransport | None = None,
) -> Any:
    """Pick the transport from configuration. Unknown values fail loudly.

    Falling back to in-process on a typo would silently drop the isolation
    requirement, and nothing downstream would look different.
    """
    resolved = settings or get_settings()
    kind = resolved.mcp_transport
    if kind == "stdio":
        return StdioMcpClient()
    if kind == "inprocess":
        return InProcessMcpClient(catalog, transport)
    raise RuntimeError(
        f"unknown mcp_transport: {kind!r} (expected 'stdio' or 'inprocess'; "
        "streamable-http is not implemented, see docs/design/README.md deviation 11)"
    )


def _child_env(token: str) -> dict[str, str]:
    import os

    env = dict(os.environ)
    env["COGNIWORK_MCP_TOKEN"] = token
    return env
