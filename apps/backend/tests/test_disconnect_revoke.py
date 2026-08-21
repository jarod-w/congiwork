"""断开连接必须撤销第三方授权（P0-05 §5、§10 验收 2）。

删本地凭据 + 撤自己的 Scope 只解决了一半：用户点了「断开」，Google / GitHub
那边的授权若还活着，用户看到的和实际发生的就是两回事。
"""

from __future__ import annotations

from uuid import UUID

from cogniwork.core.config import get_settings

from .conftest import auth_header


def _prefix() -> str:
    return get_settings().api_prefix


def _connect(client, headers, provider: str) -> str:
    started = client.post(
        f"{_prefix()}/tools/connections", headers=headers, json={"provider": provider}
    )
    assert started.status_code == 200, started.text
    return started.json()["connection"]["id"]


def _revoke_calls(transport) -> list[dict]:
    return [
        call
        for call in transport.calls
        if "revoke" in call["url"] or ("/applications/" in call["url"] and "/grant" in call["url"])
    ]


def test_google_disconnect_calls_the_revoke_endpoint(client, registered):
    from cogniwork.main import app

    headers = auth_header(registered["token"])
    connection_id = _connect(client, headers, "gcal")
    transport = app.state.tools.transport
    transport.calls.clear()

    gone = client.delete(f"{_prefix()}/tools/connections/{connection_id}", headers=headers)
    assert gone.status_code == 200, gone.text
    assert gone.json()["upstream_revoked"] is True

    calls = _revoke_calls(transport)
    assert len(calls) == 1, transport.calls
    assert calls[0]["url"] == "https://oauth2.googleapis.com/revoke"
    assert calls[0]["method"] == "POST"
    # token 走参数，且记录里必须是脱敏的（硬约束 9）
    assert calls[0]["params"]["token"] == "[redacted]"
    assert app.state.tools.store.get_credential(UUID(connection_id)) is None


def test_github_disconnect_deletes_the_grant(client, registered):
    from cogniwork.main import app

    headers = auth_header(registered["token"])
    connection_id = _connect(client, headers, "github")
    transport = app.state.tools.transport
    transport.calls.clear()

    gone = client.delete(f"{_prefix()}/tools/connections/{connection_id}", headers=headers)
    assert gone.json()["upstream_revoked"] is True
    calls = _revoke_calls(transport)
    assert len(calls) == 1
    assert calls[0]["method"] == "DELETE"
    assert "/grant" in calls[0]["url"]
    assert calls[0]["json"]["access_token"] == "[redacted]"


def test_notion_disconnect_says_so_instead_of_pretending(client, registered):
    """Notion 没有 token 撤销端点。不假装撤掉了 —— 把实情回给前端。"""
    headers = auth_header(registered["token"])
    connection_id = _connect(client, headers, "notion")
    gone = client.delete(f"{_prefix()}/tools/connections/{connection_id}", headers=headers)
    body = gone.json()
    assert body["deleted"] is True
    assert body["upstream_revoked"] is False
    assert body["detail"] == "provider_has_no_revoke_endpoint"


def test_revoke_failure_still_removes_the_local_credential(client, registered):
    """上游撤销失败不该把用户锁在一个连着的状态里。本地不留是我们能保证的部分。"""
    from cogniwork.core.errors import UpstreamError
    from cogniwork.main import app

    headers = auth_header(registered["token"])
    connection_id = _connect(client, headers, "gcal")
    tools = app.state.tools
    original = tools.transport.request

    def _boom(method, url, **kwargs):
        if "revoke" in url:
            raise UpstreamError("Google is down.", details={"status": 503})
        return original(method, url, **kwargs)

    tools.transport.request = _boom
    try:
        gone = client.delete(f"{_prefix()}/tools/connections/{connection_id}", headers=headers)
    finally:
        tools.transport.request = original

    assert gone.status_code == 200
    assert gone.json()["upstream_revoked"] is False
    assert tools.store.get_credential(UUID(connection_id)) is None
    remaining = tools.store.get_connection(UUID(registered["id"]), UUID(connection_id))
    assert remaining.status == "revoked"
    assert remaining.last_error["code"] == "revoke_failed"


def test_disconnect_revokes_before_deleting_the_credential(client, registered):
    """顺序守护：先删凭据就没 token 可撤了。"""
    from cogniwork.main import app

    headers = auth_header(registered["token"])
    connection_id = _connect(client, headers, "gcal")
    tools = app.state.tools
    order: list[str] = []
    original_request = tools.transport.request
    original_delete = tools.store.delete_credential

    def _traced_request(method, url, **kwargs):
        if "revoke" in url:
            order.append("revoke")
        return original_request(method, url, **kwargs)

    def _traced_delete(connection):
        order.append("delete_credential")
        return original_delete(connection)

    tools.transport.request = _traced_request
    tools.store.delete_credential = _traced_delete
    try:
        client.delete(f"{_prefix()}/tools/connections/{connection_id}", headers=headers)
    finally:
        tools.transport.request = original_request
        tools.store.delete_credential = original_delete

    assert order == ["revoke", "delete_credential"]
