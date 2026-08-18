"""认证 API。"""

from __future__ import annotations

from cogniwork.core.config import get_settings
from cogniwork.core.errors import ErrorCode


def _prefix() -> str:
    return get_settings().api_prefix


def test_register_and_me(client):
    response = client.post(
        f"{_prefix()}/auth/register",
        json={"email": "Ada@Example.com", "password": "a-strong-password"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["account"]["email"] == "ada@example.com"
    assert "password" not in body
    assert "password_hash" not in body["account"]

    me = client.get(
        f"{_prefix()}/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "ada@example.com"


def test_duplicate_email_is_conflict(client):
    payload = {"email": "dup@example.com", "password": "a-strong-password"}
    assert client.post(f"{_prefix()}/auth/register", json=payload).status_code == 201
    again = client.post(f"{_prefix()}/auth/register", json=payload)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == ErrorCode.CONFLICT


def test_login_success_and_wrong_password(client):
    client.post(
        f"{_prefix()}/auth/register",
        json={"email": "login@example.com", "password": "a-strong-password"},
    )
    ok = client.post(
        f"{_prefix()}/auth/login",
        json={"email": "login@example.com", "password": "a-strong-password"},
    )
    assert ok.status_code == 200
    assert ok.json()["access_token"]

    bad = client.post(
        f"{_prefix()}/auth/login",
        json={"email": "login@example.com", "password": "wrong-password"},
    )
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == ErrorCode.UNAUTHORIZED
    assert "password" not in bad.text.lower() or "invalid email or password" in bad.json()["error"]["message"].lower()


def test_login_unknown_email_same_message(client):
    missing = client.post(
        f"{_prefix()}/auth/login",
        json={"email": "nobody@example.com", "password": "a-strong-password"},
    )
    assert missing.status_code == 401
    assert missing.json()["error"]["message"] == "Invalid email or password."


def test_me_requires_bearer_token(client):
    response = client.get(f"{_prefix()}/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == ErrorCode.UNAUTHORIZED


def test_validation_error_uses_standard_shape_and_hides_password(client):
    response = client.post(
        f"{_prefix()}/auth/register",
        json={"email": "not-an-email", "password": "short"},
    )
    assert response.status_code == 400
    body = response.json()
    assert set(body["error"]) == {"code", "message", "details", "trace_id"}
    assert body["error"]["code"] == ErrorCode.INVALID_REQUEST
    assert "short" not in str(body)


def test_register_idempotency_key_replays(client):
    headers = {"Idempotency-Key": "reg-1"}
    payload = {"email": "idem@example.com", "password": "a-strong-password"}
    first = client.post(f"{_prefix()}/auth/register", json=payload, headers=headers)
    second = client.post(f"{_prefix()}/auth/register", json=payload, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["account"]["id"] == second.json()["account"]["id"]


def test_register_idempotency_key_conflict_on_different_body(client):
    headers = {"Idempotency-Key": "reg-2"}
    client.post(
        f"{_prefix()}/auth/register",
        json={"email": "one@example.com", "password": "a-strong-password"},
        headers=headers,
    )
    clash = client.post(
        f"{_prefix()}/auth/register",
        json={"email": "two@example.com", "password": "a-strong-password"},
        headers=headers,
    )
    assert clash.status_code == 409
