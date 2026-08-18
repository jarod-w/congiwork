"""授权 / 撤销 API。"""

from __future__ import annotations

from cogniwork.consent.models import ConsentAction, ConsentDecision, Risk
from cogniwork.consent.service import ConsentService
from cogniwork.core.config import get_settings
from cogniwork.core.errors import ErrorCode
from cogniwork.main import app

from .conftest import auth_header


def _prefix() -> str:
    return get_settings().api_prefix


def test_grant_requires_auth(client):
    response = client.post(
        f"{_prefix()}/consent",
        json={"scope_key": "tool:notion:read", "always_allow": True},
    )
    assert response.status_code == 401


def test_grant_unknown_scope(client, registered):
    response = client.post(
        f"{_prefix()}/consent",
        json={"scope_key": "tool:slack:read", "always_allow": True},
        headers=auth_header(registered["token"]),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == ErrorCode.INVALID_REQUEST


def test_grant_then_check_allows_and_revoke_denies(client, registered, registry):
    token = registered["token"]
    user_id = registered["id"]
    scope_key = "tool:notion:read"
    version = registry.require(scope_key).consent_text_version

    granted = client.post(
        f"{_prefix()}/consent",
        json={
            "scope_key": scope_key,
            "always_allow": True,
            "consent_text_version": version,
        },
        headers=auth_header(token),
    )
    assert granted.status_code == 200
    assert granted.json()["action"] == ConsentAction.GRANTED

    svc = ConsentService(app.state.consent_store, registry)
    assert svc.check(user_id, scope_key, Risk.READ) is ConsentDecision.ALLOW

    revoked = client.delete(
        f"{_prefix()}/consent/{scope_key}",
        headers=auth_header(token),
    )
    assert revoked.status_code == 200
    body = revoked.json()
    assert body["action"] == ConsentAction.REVOKED
    assert body["purge_requested"] is False
    assert body["purge_completed"] is False
    assert body["purge_supported"] is False

    assert svc.check(user_id, scope_key, Risk.READ) is ConsentDecision.DENY


def test_revoke_does_not_purge_by_default(client, registered, registry):
    token = registered["token"]
    scope_key = "tool:gmail:read"
    client.post(
        f"{_prefix()}/consent",
        json={
            "scope_key": scope_key,
            "always_allow": True,
            "consent_text_version": registry.require(scope_key).consent_text_version,
        },
        headers=auth_header(token),
    )
    revoked = client.delete(
        f"{_prefix()}/consent/{scope_key}",
        params={"purge_data": False},
        headers=auth_header(token),
    )
    assert revoked.json()["purge_requested"] is False


def test_revoke_unknown_grant_is_not_found(client, registered):
    response = client.delete(
        f"{_prefix()}/consent/tool:notion:read",
        headers=auth_header(registered["token"]),
    )
    assert response.status_code == 404


def test_stale_consent_text_version_is_conflict(client, registered, registry):
    scope_key = "tool:notion:read"
    response = client.post(
        f"{_prefix()}/consent",
        json={
            "scope_key": scope_key,
            "always_allow": True,
            "consent_text_version": "not-the-current-version",
        },
        headers=auth_header(registered["token"]),
    )
    assert response.status_code == 409
    assert response.json()["error"]["details"]["expected_version"] == (
        registry.require(scope_key).consent_text_version
    )


def test_irreversible_grant_still_requires_approval(client, registered, registry):
    """硬约束 4：授权 API 存 always_allow 也不能让 irreversible 免审批。"""
    token = registered["token"]
    user_id = registered["id"]
    scope_key = "tool:gmail:send"
    client.post(
        f"{_prefix()}/consent",
        json={
            "scope_key": scope_key,
            "always_allow": True,
            "consent_text_version": registry.require(scope_key).consent_text_version,
        },
        headers=auth_header(token),
    )
    svc = ConsentService(app.state.consent_store, registry)
    assert svc.check(user_id, scope_key, Risk.IRREVERSIBLE) is ConsentDecision.REQUIRE_APPROVAL


def test_grant_is_per_user(client, registry):
    first = client.post(
        f"{_prefix()}/auth/register",
        json={"email": "one@example.com", "password": "a-strong-password"},
    ).json()
    second = client.post(
        f"{_prefix()}/auth/register",
        json={"email": "two@example.com", "password": "a-strong-password"},
    ).json()
    scope_key = "tool:notion:read"
    client.post(
        f"{_prefix()}/consent",
        json={
            "scope_key": scope_key,
            "always_allow": True,
            "consent_text_version": registry.require(scope_key).consent_text_version,
        },
        headers=auth_header(first["access_token"]),
    )
    svc = ConsentService(app.state.consent_store, registry)
    assert svc.check(first["account"]["id"], scope_key, Risk.READ) is ConsentDecision.ALLOW
    assert svc.check(second["account"]["id"], scope_key, Risk.READ) is ConsentDecision.DENY
