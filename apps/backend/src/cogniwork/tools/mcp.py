"""MCP JSON-RPC 2.0 subset: initialize / tools/list / tools/call (P0-05 M1).

stdio servers are isolated processes. Tests use the in-process client so a
crashed connector cannot take down the API.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

from cogniwork.runtime.tools.spec import ToolResult
from cogniwork.tools.catalog import ToolCatalog, load_catalog
from cogniwork.tools.http import HttpTransport
from cogniwork.tools.providers import invoke_provider
from cogniwork.tools.vault import redact_obj


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
    def call(
        self, provider: str, mcp_name: str, arguments: dict[str, Any], token: str
    ) -> ToolResult:
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": mcp_name, "arguments": arguments},
            }
        )
        proc = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "cogniwork.tools.mcp_server", "--provider", provider],
            input=payload + "\n",
            capture_output=True,
            text=True,
            env=_child_env(token),
            check=False,
            timeout=45,
        )
        if proc.returncode != 0:
            return ToolResult(mcp_name, False, "The connector process failed.")
        line = (proc.stdout or "").splitlines()[-1] if proc.stdout else "{}"
        rpc = json.loads(line)
        payload = rpc.get("result") or {}
        return ToolResult(
            f"{provider}.{mcp_name}",
            bool(payload.get("ok")),
            str(payload.get("content") or ""),
            dict(payload.get("data") or {}),
        )


def _child_env(token: str) -> dict[str, str]:
    import os

    env = dict(os.environ)
    env["COGNIWORK_MCP_TOKEN"] = token
    return env
