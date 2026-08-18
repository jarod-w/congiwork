"""GET /api/v1/scopes。"""

from __future__ import annotations

from cogniwork.core.config import get_settings


def test_scopes_endpoint_exposes_registry(client, registry):
    settings = get_settings()
    response = client.get(f"{settings.api_prefix}/scopes")
    assert response.status_code == 200
    body = response.json()
    assert body["locale"] == settings.default_locale
    keys = {item["key"] for item in body["scopes"]}
    assert keys == set(registry.keys())
    sample = next(item for item in body["scopes"] if item["key"] == "tool:gmail:read")
    assert set(sample["copy"]) == {
        "display_name",
        "collects",
        "retention",
        "degraded_behavior",
    }
    assert sample["consent_text_version"]
    assert sample["risk"] == "read"
    assert sample["trust_level"] == "L2"


def test_scopes_endpoint_uses_fallback_for_unknown_locale(client):
    settings = get_settings()
    response = client.get(f"{settings.api_prefix}/scopes", params={"locale": "fr-FR"})
    assert response.status_code == 200
    assert response.json()["locale"] == settings.fallback_locale


def test_scopes_endpoint_is_public(client):
    response = client.get(f"{get_settings().api_prefix}/scopes")
    assert response.status_code == 200
    assert "authorization" not in response.request.headers
