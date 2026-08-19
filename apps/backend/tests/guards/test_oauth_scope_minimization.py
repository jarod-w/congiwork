"""CI 守护：申请的 OAuth scope ⊆ 已开启 CogniWork Scope 映射的 OAuth scope（P0-05 §10 验收 4）。"""

from __future__ import annotations

from cogniwork.consent.registry import get_registry
from cogniwork.tools.catalog import load_catalog


def test_catalog_oauth_never_exceeds_scope_registry():
    catalog = load_catalog()
    registry = get_registry()
    for provider in catalog.providers:
        for tool in provider.tools:
            spec = registry.get(tool.scope_key)
            assert spec is not None, f"{tool.name} maps to unregistered {tool.scope_key}"
            assert spec.risk.value == tool.risk.value or tool.risk.value == "irreversible"
        granted = catalog.scopes_for_provider(provider.id)
        oauth = catalog.oauth_scopes_for(granted)
        allowed = []
        for key in granted:
            allowed.extend(list(registry.require(key).third_party_scopes))
        extra = [item for item in oauth if item not in allowed]
        assert not extra, f"{provider.id} would request extra OAuth scopes: {extra}"


def test_read_connection_does_not_pull_write_oauth():
    catalog = load_catalog()
    gmail_read = catalog.oauth_scopes_for(["tool:gmail:read"])
    assert all("gmail.send" not in item and "gmail.compose" not in item for item in gmail_read)
    gcal_read = catalog.oauth_scopes_for(["tool:gcal:read"])
    assert all("calendar.events" not in item for item in gcal_read)
