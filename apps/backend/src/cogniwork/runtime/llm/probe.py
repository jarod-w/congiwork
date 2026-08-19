"""Capability probe for custom providers (P0-03 §7.1 ③).

If the model cannot do forced tool-use schema, we store that and refuse
to route tool-using tasks to it. We never silently parse free text as
tool calls.
"""

from __future__ import annotations

import json
from typing import Any

from cogniwork.core.config import get_settings
from cogniwork.core.errors import InvalidRequest
from cogniwork.runtime.llm.ssrf import assert_public_https, default_resolve

_PROBE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ping",
            "description": "Capability probe. Call this once.",
            "parameters": {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
            },
        },
    }
]


def probe_provider(base_url: str, api_key: str, model: str) -> dict[str, Any]:
    settings = get_settings()
    if settings.llm_provider == "stub" or settings.oauth_stub:
        # Tests never hit a network. A stub probe still records the shape.
        return {
            "tool_use": True,
            "streaming": False,
            "vision": False,
            "json_schema": True,
            "max_context": 128000,
            "probed": False,
        }
    resolved = assert_public_https(base_url)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Call ping with ok=true."}],
        "tools": _PROBE_TOOLS,
        "tool_choice": {"type": "function", "function": {"name": "ping"}},
    }
    body = _pinned_post(resolved, api_key, payload)
    tool_use = _has_tool_call(body)
    return {
        "tool_use": tool_use,
        "streaming": False,
        "vision": False,
        "json_schema": tool_use,
        "max_context": 128000,
        "probed": True,
    }


def _has_tool_call(body: dict[str, Any]) -> bool:
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return False
    return bool(message.get("tool_calls"))


def _pinned_post(resolved: Any, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST to the pinned IP. Do not follow redirects. Do not re-resolve DNS."""
    import http.client
    import ssl

    # Re-check the pinned IP immediately before connecting.
    assert_public_https(resolved.safe_url, resolver=lambda _host: [resolved.pinned_ip])
    context = ssl.create_default_context()
    conn = http.client.HTTPSConnection(
        resolved.pinned_ip,
        resolved.port,
        timeout=15,
        context=context,
    )
    try:
        raw = json.dumps(payload).encode()
        conn.request(
            "POST",
            "/v1/chat/completions",
            body=raw,
            headers={
                "Host": resolved.host,
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Content-Length": str(len(raw)),
            },
        )
        response = conn.getresponse()
        if 300 <= response.status < 400:
            raise InvalidRequest(
                "Custom model URLs must not redirect.",
                details={"reason": "redirect"},
            )
        data = response.read(256_000)
        if response.status >= 400:
            raise InvalidRequest(
                "The custom model service rejected the capability probe.",
                details={"status": response.status},
            )
        return json.loads(data.decode() or "{}")
    finally:
        conn.close()


def custom_route_allowed(
    *,
    granted: bool,
    capabilities: dict[str, Any] | None,
    needs_tool_use: bool,
) -> tuple[bool, str | None]:
    if not granted:
        return False, "custom_scope_denied"
    if not capabilities:
        return False, "not_configured"
    if needs_tool_use and not capabilities.get("tool_use"):
        return False, "no_tool_use"
    return True, None


# Keep default_resolve imported so tests can monkeypatch through this module.
_ = default_resolve
