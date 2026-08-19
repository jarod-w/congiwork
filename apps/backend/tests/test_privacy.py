"""隐私中心：导出、删除、设置开关默认关闭（B6）、审计脱敏。"""

from __future__ import annotations

from cogniwork.core.config import get_settings

from .conftest import auth_header


def _prefix() -> str:
    return get_settings().api_prefix


def test_privacy_overview_and_settings_default_off(client, registered):
    headers = auth_header(registered["token"])
    overview = client.get(f"{_prefix()}/privacy", headers=headers)
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert body["settings"]["episodic_auto_cleanup"] is False
    assert body["boundaries"]["admin_cannot_enable"] is True
    assert "United States" in body["boundaries"]["markets"]

    patched = client.patch(
        f"{_prefix()}/privacy/settings",
        headers=headers,
        json={"episodic_auto_cleanup": True, "episodic_retention_months": 6},
    )
    assert patched.json()["episodic_auto_cleanup"] is True
    assert patched.json()["episodic_retention_months"] == 6


def test_export_and_delete_account(client, registered):
    headers = auth_header(registered["token"])
    client.post(
        f"{_prefix()}/memories",
        headers=headers,
        json={"type": "preference", "content": "Keep emails short."},
    )
    exported = client.get(f"{_prefix()}/privacy/export", headers=headers)
    assert exported.status_code == 200
    assert exported.json()["memories"]["count"] >= 1

    deleted = client.delete(f"{_prefix()}/privacy/account", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["deleted"]["account"] is True
    me = client.get(f"{_prefix()}/auth/me", headers=headers)
    assert me.status_code == 401


def test_audit_has_no_plaintext_body(client, registered):
    headers = auth_header(registered["token"])
    client.post(
        f"{_prefix()}/tasks",
        headers=headers,
        json={"message": "Turn this note into a weekly report. SECRET-TOKEN-XYZ"},
    )
    import time

    time.sleep(0.2)
    audit = client.get(f"{_prefix()}/privacy/audit", headers=headers)
    assert audit.status_code == 200
    blob = audit.text
    assert "SECRET-TOKEN-XYZ" not in blob
