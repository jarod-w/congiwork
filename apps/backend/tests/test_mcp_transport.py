"""MCP 传输形态（P0-05 §3 / M1）。

这一组的意义在于 stdio 那条路径**真的被走过**。executor 曾经恒用 in-process
client，`mcp_transport` 配置项无人读 —— 于是「连接器进程崩溃只影响该用户该连接」
在实际路径上并不成立，而没有任何测试会因此变红。
"""

from __future__ import annotations

import pytest

from cogniwork.core.config import Settings
from cogniwork.tools.catalog import load_catalog
from cogniwork.tools.http import StubTransport
from cogniwork.tools.mcp import InProcessMcpClient, StdioMcpClient, build_mcp_client
from cogniwork.tools.service import ToolService


def test_transport_comes_from_configuration():
    stdio = build_mcp_client(Settings(mcp_transport="stdio"))
    assert isinstance(stdio, StdioMcpClient)
    inprocess = build_mcp_client(Settings(mcp_transport="inprocess"))
    assert isinstance(inprocess, InProcessMcpClient)


def test_unknown_transport_fails_loudly():
    """静默回落到 in-process 会悄悄取消隔离要求，且外部看不出区别。"""
    with pytest.raises(RuntimeError, match="unknown mcp_transport"):
        build_mcp_client(Settings(mcp_transport="streamable-http"))


def test_executor_honours_the_configured_transport():
    from cogniwork.tools.executor import McpExecutor

    tools = ToolService(settings=Settings(oauth_stub=True, mcp_transport="stdio"))
    executor = McpExecutor(tools, settings=Settings(mcp_transport="stdio"))
    assert isinstance(executor._client, StdioMcpClient)


def test_stdio_client_runs_the_connector_in_its_own_process():
    """真起一个子进程。子进程继承 COGNIWORK_OAUTH_STUB=true，所以不出网。"""
    client = StdioMcpClient(timeout_s=60)
    result = client.call("gcal", "list_events", {"max_results": 5}, "cw-canary-access")
    assert result.ok is True, result.content
    assert result.name == "gcal.list_events"
    assert "Events:" in result.content


def test_unknown_provider_comes_back_as_a_failed_result():
    client = StdioMcpClient(timeout_s=60)
    result = client.call("nope-not-a-provider", "list_events", {}, "cw-canary-access")
    assert result.ok is False
    assert "Unknown provider" in result.content


def test_a_crashed_connector_does_not_raise_into_the_api_process(monkeypatch):
    """隔离要求的落点：连接器怎么死，API 进程都只看到一个失败的 ToolResult。"""
    import subprocess

    class _Dead:
        returncode = 139  # SIGSEGV
        stdout = ""
        stderr = "Segmentation fault"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Dead())
    result = StdioMcpClient().call("gcal", "list_events", {}, "cw-canary-access")
    assert result.ok is False
    assert result.data == {"provider": "gcal", "exit_code": 139}
    assert "Other connectors still work" in result.content


def test_a_hung_connector_times_out_instead_of_blocking_forever(monkeypatch):
    import subprocess

    def _hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="mcp_server", timeout=45)

    monkeypatch.setattr(subprocess, "run", _hang)
    result = StdioMcpClient().call("gmail", "list_messages", {}, "cw-canary-access")
    assert result.ok is False
    assert result.data.get("timeout") is True


def test_stdio_and_inprocess_agree_on_the_result_shape():
    """换传输不该改变 Runtime 看到的东西。"""
    args = {"max_results": 3}
    stdio = StdioMcpClient(timeout_s=60).call("gcal", "list_events", args, "cw-canary-access")
    inprocess = InProcessMcpClient(load_catalog(), StubTransport()).call(
        "gcal", "list_events", args, "cw-canary-access"
    )
    assert stdio.name == inprocess.name
    assert stdio.ok == inprocess.ok
    assert stdio.content == inprocess.content
    assert set(stdio.data) == set(inprocess.data)
