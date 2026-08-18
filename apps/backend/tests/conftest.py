from __future__ import annotations

import os

# 必须在 import cogniwork 之前：Settings 是 lru_cache，单测默认走内存实现。
# CI 会预先设置 COGNIWORK_STORE_BACKEND=postgres，setdefault 不会覆盖。
os.environ.setdefault("COGNIWORK_STORE_BACKEND", "memory")
os.environ.setdefault("COGNIWORK_JWT_SECRET", "test-jwt-secret-32-bytes-minimum!!")
os.environ.setdefault("COGNIWORK_IP_HASH_PEPPER", "test-ip-pepper")
os.environ.setdefault("COGNIWORK_LLM_PROVIDER", "stub")

import pytest
from fastapi.testclient import TestClient

from cogniwork.consent.registry import load_registry
from cogniwork.core.config import get_settings

get_settings.cache_clear()


@pytest.fixture(scope="session")
def registry():
    return load_registry()


@pytest.fixture
def client():
    from cogniwork.main import app

    with TestClient(app) as test_client:
        yield test_client
        consent_store = getattr(app.state, "consent_store", None)
        account_store = getattr(app.state, "account_store", None)
        if consent_store is not None and hasattr(consent_store, "clear"):
            consent_store.clear()
        if account_store is not None and hasattr(account_store, "clear"):
            account_store.clear()
        task_store = getattr(app.state, "task_store", None)
        if task_store is not None and hasattr(task_store, "clear"):
            task_store.clear()
        events = getattr(app.state, "event_broker", None)
        if events is not None and hasattr(events, "clear"):
            events.clear()
        audit = getattr(app.state, "audit_log", None)
        if audit is not None and hasattr(audit, "clear"):
            audit.clear()
        idem = getattr(app.state, "idempotency", None)
        if isinstance(idem, dict):
            idem.clear()


@pytest.fixture
def registered(client: TestClient) -> dict[str, str]:
    response = client.post(
        f"{get_settings().api_prefix}/auth/register",
        json={"email": "user@example.com", "password": "a-strong-password"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return {"token": body["access_token"], "id": body["account"]["id"]}


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
