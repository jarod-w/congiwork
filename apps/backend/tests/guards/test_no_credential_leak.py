"""CI 守护：凭据不落明文（硬约束 9 / P0-05 §10.6）。"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "cogniwork"
TOOLS = SRC / "tools"

_SECRET_NAMES = {"access_token", "refresh_token", "id_token", "client_secret"}


def _python_files() -> list[Path]:
    return sorted(p for p in TOOLS.rglob("*.py") if "__pycache__" not in p.parts)


def test_tools_do_not_log_token_fields():
    """logger / print 的参数里不得直接出现 token 字段名。"""
    offenders: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = ""
                if isinstance(func, ast.Attribute):
                    name = func.attr
                elif isinstance(func, ast.Name):
                    name = func.id
                if name not in {"info", "debug", "warning", "error", "exception", "print"}:
                    continue
                dump = ast.dump(node)
                for secret in _SECRET_NAMES:
                    if secret in dump and "redact" not in dump.lower():
                        rel = path.relative_to(SRC).as_posix()
                        offenders.append(f"{rel}:{node.lineno}:{secret}")
    assert not offenders, "凭据字段出现在日志调用里:\n  " + "\n  ".join(offenders)


def test_canary_token_does_not_appear_in_tool_result(client, registered):
    from cogniwork.core.config import get_settings
    from cogniwork.runtime.tools.registry import ToolRegistry
    from cogniwork.runtime.tools.router import ToolRouter
    from cogniwork.tools.catalog import load_catalog

    prefix = get_settings().api_prefix
    headers = {"Authorization": f"Bearer {registered['token']}"}
    client.post(f"{prefix}/tools/connections", headers=headers, json={"provider": "notion"})
    from cogniwork.main import app

    spec = load_catalog().tool("notion.search")
    assert spec is not None
    registry = ToolRegistry()
    registry.register(spec.to_spec(), app.state.mcp_executor)
    router = ToolRouter(registry, app.state.consent_service, app.state.audit_log)
    result = router.invoke(
        user_id=registered["id"],
        name="notion.search",
        arguments={"query": "q3 plan"},
        context={"user_id": registered["id"], "surface": "web"},
    )
    assert result.ok is True
    assert "cw-canary-access" not in result.content
    assert "cw-canary-access" not in str(result.data)
