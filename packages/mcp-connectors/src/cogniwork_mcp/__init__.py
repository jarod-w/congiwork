"""Re-export the stdio MCP server so `packages/mcp-connectors` is not empty."""

from cogniwork.tools.mcp_server import main

__all__ = ["main"]
