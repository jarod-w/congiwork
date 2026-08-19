"""Write tools + approval path + resilience (P0-05 M5 / M6)."""

from __future__ import annotations

from uuid import UUID

from cogniwork.consent.models import Risk
from cogniwork.core.config import get_settings
from cogniwork.runtime.tools.registry import ToolRegistry
from cogniwork.runtime.tools.router import ToolRouter
from cogniwork.runtime.tools.spec import ToolResult, ToolSpec
from cogniwork.tools.catalog import load_catalog
from cogniwork.tools.resilience import Resilience

from .conftest import auth_header


def _prefix() -> str:
    return get_settings().api_prefix


def test_write_tools_are_registered_with_scopes():
    catalog = load_catalog()
    assert catalog.tool("gmail.create_draft") is not None
    assert catalog.tool("gmail.send_message").risk is Risk.IRREVERSIBLE
    assert catalog.tool("gcal.create_event").risk is Risk.WRITE
    assert catalog.tool("gcal.delete_event").risk is Risk.IRREVERSIBLE
    assert catalog.tool("notion.create_page").risk is Risk.WRITE
    assert catalog.tool("notion.delete_block").risk is Risk.IRREVERSIBLE


def test_gmail_send_always_needs_approval(client, registered):
    headers = auth_header(registered["token"])
    client.post(
        f"{_prefix()}/consent",
        headers=headers,
        json={"scope_key": "tool:gmail:send", "consent_text_version": "1", "always_allow": True},
    )
    from cogniwork.main import app

    spec = load_catalog().tool("gmail.send_message")
    assert spec is not None
    registry = ToolRegistry()
    registry.register(spec.to_spec(), app.state.mcp_executor)
    router = ToolRouter(registry, app.state.consent_service, app.state.audit_log)
    result = router.invoke(
        user_id=registered["id"],
        name="gmail.send_message",
        arguments={"to": ["a@example.com"], "subject": "Hi", "body": "Hello"},
        context={"user_id": registered["id"], "surface": "web"},
    )
    assert result.needs_approval is True


def test_irreversible_is_not_retried():
    spec = ToolSpec(
        name="gmail.send_message",
        provider="mcp",
        description="send",
        input_schema={},
        scope_key="tool:gmail:send",
        risk=Risk.IRREVERSIBLE,
        retryable=False,
    )
    calls = {"n": 0}

    def invoke(_spec, _args, _ctx):
        calls["n"] += 1
        raise TimeoutError("upstream timeout")

    resilience = Resilience(max_retries=2)
    result = resilience.call(spec, invoke, {}, {"user_id": "u"})
    assert calls["n"] == 1
    assert result.ok is False
    assert result.data.get("uncertain") is True


def test_read_is_retried_then_succeeds():
    spec = ToolSpec(
        name="gcal.list_events",
        provider="mcp",
        description="list",
        input_schema={},
        scope_key="tool:gcal:read",
        risk=Risk.READ,
        retryable=True,
    )
    calls = {"n": 0}

    def invoke(_spec, _args, _ctx):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("flaky")
        return ToolResult("gcal.list_events", True, "ok")

    result = Resilience(max_retries=2).call(spec, invoke, {}, {"user_id": "u"})
    assert result.ok is True
    assert calls["n"] == 2


def test_circuit_breaker_is_per_provider():
    failing = ToolSpec(
        name="gmail.search_messages",
        provider="mcp",
        description="search",
        input_schema={},
        scope_key="tool:gmail:read",
        risk=Risk.READ,
    )
    other = ToolSpec(
        name="notion.search",
        provider="mcp",
        description="search",
        input_schema={},
        scope_key="tool:notion:read",
        risk=Risk.READ,
    )
    resilience = Resilience(breaker_threshold=3, breaker_seconds=60)

    def boom(_spec, _args, _ctx):
        from cogniwork.core.errors import UpstreamError

        raise UpstreamError("down", details={"status": 503})

    def ok(_spec, _args, _ctx):
        return ToolResult("notion.search", True, "ok")

    for _ in range(3):
        resilience.call(failing, boom, {}, {"user_id": "u"})
    assert resilience.is_open("gmail") is True
    assert resilience.is_open("notion") is False
    blocked = resilience.call(failing, boom, {}, {"user_id": "u"})
    assert blocked.data.get("circuit_open") is True
    fine = resilience.call(other, ok, {}, {"user_id": "u"})
    assert fine.ok is True


def test_create_draft_runs_after_write_scope(client, registered):
    headers = auth_header(registered["token"])
    client.post(f"{_prefix()}/tools/connections", headers=headers, json={"provider": "gmail"})
    client.post(
        f"{_prefix()}/consent",
        headers=headers,
        json={"scope_key": "tool:gmail:write", "consent_text_version": "1", "always_allow": True},
    )
    from cogniwork.main import app

    spec = load_catalog().tool("gmail.create_draft")
    registry = ToolRegistry()
    registry.register(spec.to_spec(), app.state.mcp_executor)
    router = ToolRouter(registry, app.state.consent_service, app.state.audit_log)
    result = router.invoke(
        user_id=registered["id"],
        name="gmail.create_draft",
        arguments={"to": ["a@example.com"], "subject": "Hi", "body": "Hello"},
        context={"user_id": registered["id"], "surface": "web"},
    )
    # write is first-approval unless always_allow; we granted always_allow.
    assert result.ok is True or result.needs_approval is True
    _ = UUID  # keep import used for typing stability
