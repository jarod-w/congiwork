"""MCP connections, vault, OAuth scope minimization, GitHub approval carrier."""

from __future__ import annotations

from uuid import UUID

from cogniwork.consent.models import Risk
from cogniwork.core.config import get_settings
from cogniwork.runtime.digest import InMemoryAuditLog
from cogniwork.runtime.tools.registry import ToolRegistry, build_runtime_registry
from cogniwork.runtime.tools.router import ToolRouter
from cogniwork.tools.catalog import load_catalog
from cogniwork.tools.vault import open_bundle, redact_obj, seal_bundle

from .conftest import auth_header


class _Dummy:
    def invoke(self, spec, arguments, context):
        raise AssertionError("executor should not run in this test")


def _prefix() -> str:
    return get_settings().api_prefix


def test_catalog_oauth_scopes_are_subset_of_enabled_scopes():
    catalog = load_catalog()
    requested = catalog.oauth_scopes_for(["tool:gcal:read"])
    assert requested == ["https://www.googleapis.com/auth/calendar.readonly"]
    gmail = catalog.oauth_scopes_for(["tool:gmail:read"])
    assert gmail == ["https://www.googleapis.com/auth/gmail.readonly"]
    assert "https://www.googleapis.com/auth/gmail.send" not in gmail


def test_connect_invoke_audit_disconnect(client, registered):
    headers = auth_header(registered["token"])
    started = client.post(
        f"{_prefix()}/tools/connections",
        headers=headers,
        json={"provider": "gcal"},
    )
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["status"] == "active"
    connection_id = body["connection"]["id"]
    scopes = body["connection"]["oauth_scopes"]
    assert any("calendar.readonly" in scope for scope in scopes)
    assert all("calendar.events" not in scope for scope in scopes)

    from cogniwork.main import app

    tools = app.state.tools
    executor = app.state.mcp_executor
    registry = ToolRegistry()
    spec = load_catalog().tool("gcal.list_events")
    assert spec is not None
    registry.register(spec.to_spec(), executor)
    router = ToolRouter(registry, app.state.consent_service, app.state.audit_log)
    result = router.invoke(
        user_id=registered["id"],
        name="gcal.list_events",
        arguments={"query": "standup"},
        context={"user_id": registered["id"], "surface": "web", "task_id": None, "step_id": None},
    )
    assert result.ok is True
    assert "cw-canary-access" not in result.content
    activity = client.get(
        f"{_prefix()}/tools/connections/{connection_id}/activity",
        headers=headers,
    )
    assert activity.status_code == 200
    blob = activity.text
    assert "cw-canary-access" not in blob

    gone = client.delete(f"{_prefix()}/tools/connections/{connection_id}", headers=headers)
    assert gone.status_code == 200
    cred = tools.store.get_credential(UUID(connection_id))
    assert cred is None


def test_github_merge_always_needs_approval(client, registered):
    headers = auth_header(registered["token"])
    client.post(
        f"{_prefix()}/tools/connections",
        headers=headers,
        json={"provider": "github", "scopes": ["tool:github:read", "tool:github:write"]},
    )
    from cogniwork.main import app

    spec = load_catalog().tool("github.merge_pr")
    assert spec is not None
    assert spec.risk is Risk.IRREVERSIBLE
    registry = ToolRegistry()
    registry.register(spec.to_spec(), app.state.mcp_executor)
    router = ToolRouter(registry, app.state.consent_service, InMemoryAuditLog())
    result = router.invoke(
        user_id=registered["id"],
        name="github.merge_pr",
        arguments={"owner": "acme", "repo": "app", "number": 1},
        context={"user_id": registered["id"], "surface": "web"},
    )
    assert result.needs_approval is True


def test_vault_roundtrip_and_redaction():
    master = b"0" * 32
    bundle = {"access_token": "cw-canary-access", "refresh_token": "cw-canary-refresh"}
    ciphertext, wrapped, version = seal_bundle(bundle, master)
    opened = open_bundle(ciphertext, wrapped, master)
    assert opened["access_token"] == "cw-canary-access"
    assert redact_obj(opened)["access_token"] == "[redacted]"
    assert version == 1


def test_providers_list_comes_from_catalog(client, registered):
    headers = auth_header(registered["token"])
    listed = client.get(f"{_prefix()}/tools/providers", headers=headers)
    assert listed.status_code == 200
    ids = [row["id"] for row in listed.json()["providers"]]
    assert ids == ["gcal", "notion", "gmail", "github"]


def test_runtime_registry_includes_mcp_read_tools():
    registry = build_runtime_registry(_Dummy())
    names = {spec.name for spec in registry.specs()}
    assert "gcal.list_events" in names
    assert "notion.search" in names
    assert "gmail.search_messages" in names
    assert "github.search_code" in names
    assert "gmail.send_message" not in names
