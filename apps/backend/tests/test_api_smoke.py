"""API 冒烟测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cogniwork.consent.registry import RegistryError, get_registry
from cogniwork.core.config import get_settings
from cogniwork.core.errors import ErrorCode, PermissionDenied
from cogniwork.main import app


def test_health_reports_registry_size():
    with TestClient(app) as client:
        response = client.get(f"{get_settings().api_prefix}/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["scopes_registered"] > 0


@pytest.mark.parametrize(
    ("name", "content"),
    [
        (
            "scopes 为空",
            "version: 1\nvocabularies:\n  domain: [tool]\n  capability: [read]\n"
            "  risk: [read, write, irreversible]\n"
            "  trust_level: [L1, L2, L3, L4]\nscopes: []\n",
        ),
        ("vocabularies 缺失", "version: 1\nscopes: []\n"),
        ("整个文件是空的", "\n"),
    ],
)
def test_app_refuses_to_start_on_broken_registry(monkeypatch, tmp_path, name, content):
    """注册表坏了就起不来 —— 这是有意的行为，不是脆弱。

    快速失败的代价是一次部署失败；带病运行的代价是用户看到一张
    说不清「不开启会怎样」的授权卡片。前者便宜得多。
    """
    broken = tmp_path / "scopes.yaml"
    broken.write_text(content, encoding="utf-8")
    monkeypatch.setenv("COGNIWORK_SCOPES_PATH", str(broken))

    get_registry.cache_clear()
    try:
        with pytest.raises(RegistryError), TestClient(app):
            pass
    finally:
        get_registry.cache_clear()


def test_error_body_shape():
    """00-conventions.md §6：错误响应结构固定。"""
    err = PermissionDenied(
        "I need access to your email to continue.",
        details={"scope": "tool:gmail:read", "degraded_behavior": "Paste it here instead."},
    )
    body = err.to_body("trace-abc")
    assert set(body["error"]) == {"code", "message", "details", "trace_id"}
    assert body["error"]["code"] == ErrorCode.PERMISSION_DENIED
    assert body["error"]["trace_id"] == "trace-abc"
