"""Custom provider SSRF + capability routing (P0-03 §7.1 / M6b)."""

from __future__ import annotations

import pytest

from cogniwork.core.errors import InvalidRequest
from cogniwork.runtime.llm.probe import custom_route_allowed
from cogniwork.runtime.llm.ssrf import assert_public_https


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/v1",
        "https://127.0.0.1/v1",
        "https://10.0.0.5/v1",
        "https://192.168.1.9/v1",
        "https://172.16.4.4/v1",
        "https://169.254.169.254/latest/meta-data",
        "https://224.0.0.1/v1",
        "https://[::1]/v1",
    ],
)
def test_ssrf_rejects_private_and_non_https(url):
    with pytest.raises(InvalidRequest):
        assert_public_https(url, resolver=lambda host: [host.strip("[]")])


def test_ssrf_rejects_http_even_for_public_host():
    with pytest.raises(InvalidRequest) as exc:
        assert_public_https("http://example.com/v1", resolver=lambda _host: ["1.1.1.1"])
    assert exc.value.details.get("reason") == "scheme"


def test_dns_rebinding_pins_the_first_public_ip():
    calls: list[str] = []

    def resolver(host: str) -> list[str]:
        calls.append(host)
        if len(calls) == 1:
            return ["1.1.1.1"]
        return ["127.0.0.1"]

    resolved = assert_public_https("https://rebind.example/v1", resolver=resolver)
    assert resolved.pinned_ip == "1.1.1.1"
    # Request-time check uses the pinned IP, not a second DNS lookup.
    again = assert_public_https(resolved.safe_url, resolver=lambda _host: [resolved.pinned_ip])
    assert again.pinned_ip == "1.1.1.1"
    with pytest.raises(InvalidRequest):
        assert_public_https("https://rebind.example/v1", resolver=lambda _host: ["127.0.0.1"])


def test_pinned_client_dials_the_stored_ip(monkeypatch):
    import httpcore

    from cogniwork.runtime.llm.ssrf import pinned_httpx_client

    resolved = assert_public_https("https://rebind.example/v1", resolver=lambda _host: ["1.1.1.1"])
    seen: dict[str, object] = {}

    def fake_connect(self, host, port, timeout=None, local_address=None, socket_options=None):
        seen["host"] = host
        seen["port"] = port
        raise OSError("do not connect")

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", fake_connect)
    client = pinned_httpx_client(resolved)
    try:
        client.get("https://rebind.example/v1")
    except Exception:
        pass
    assert seen.get("host") == "1.1.1.1"
    assert seen.get("port") == 443


def test_redirect_is_rejected_by_probe_helper():
    from cogniwork.core.errors import InvalidRequest as Err
    from cogniwork.runtime.llm.ssrf import ResolvedUrl

    class FakeResp:
        status = 302

        def read(self, _n: int = 0) -> bytes:
            return b""

    class FakeConn:
        def request(self, *args, **kwargs):
            return None

        def getresponse(self):
            return FakeResp()

        def close(self):
            return None

    import cogniwork.runtime.llm.probe as probe

    monkey_resolved = ResolvedUrl(
        safe_url="https://example.com/v1",
        host="example.com",
        port=443,
        path="/v1",
        pinned_ip="1.1.1.1",
    )
    original_https = probe.http.client.HTTPSConnection if False else None
    _ = original_https
    import http.client

    def fake_conn(*args, **kwargs):
        return FakeConn()

    old = http.client.HTTPSConnection
    http.client.HTTPSConnection = fake_conn  # type: ignore[assignment]
    try:
        with pytest.raises(Err) as exc:
            probe._pinned_post(monkey_resolved, "key", {})
        assert exc.value.details.get("reason") == "redirect"
    finally:
        http.client.HTTPSConnection = old


def test_no_tool_use_is_not_routed():
    allowed, reason = custom_route_allowed(
        granted=True,
        capabilities={"tool_use": False},
        needs_tool_use=True,
    )
    assert allowed is False
    assert reason == "no_tool_use"


def test_custom_route_requires_scope(client, registered):
    from cogniwork.main import app
    from cogniwork.runtime.llm.router import RoutingRequest

    request = RoutingRequest(
        task_intent=None,
        context_tokens=0,
        needs_vision=False,
        needs_tool_use=True,
        latency_class="interactive",
        cost_tier="standard",
    )
    router = app.state.task_engine.router
    client_obj = router.client_for(request, user_id=registered["id"])
    attempts = getattr(router, "custom_attempts", [])
    assert client_obj.vendor != "openai" or not attempts
    assert attempts == []
