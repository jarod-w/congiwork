"""SSRF guards for custom LLM base_url (P0-03 §7.1 ②).

Validated on save and again before every request. DNS can change between
those two moments, so we pin the resolved IP and connect to it with the
original Host header — we never let the HTTP client re-resolve.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from cogniwork.core.errors import InvalidRequest

_BLOCKED = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
    ipaddress.ip_network("::/128"),
)


@dataclass(frozen=True, slots=True)
class ResolvedUrl:
    safe_url: str
    host: str
    port: int
    path: str
    pinned_ip: str


def assert_public_https(url: str, *, resolver: AnyResolver | None = None) -> ResolvedUrl:
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() != "https":
        raise InvalidRequest(
            "Custom model URLs must use https.",
            details={"reason": "scheme"},
        )
    if parsed.username or parsed.password:
        raise InvalidRequest("Custom model URLs cannot include credentials.")
    host = parsed.hostname
    if not host:
        raise InvalidRequest("Custom model URLs need a hostname.")
    port = parsed.port or 443
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    addresses = (resolver or default_resolve)(host)
    if not addresses:
        raise InvalidRequest("Could not resolve the model service hostname.")
    public: list[str] = []
    for address in addresses:
        _assert_public_ip(address)
        public.append(address)
    return ResolvedUrl(
        safe_url=f"https://{host}:{port}{path}" if port != 443 else f"https://{host}{path}",
        host=host,
        port=port,
        path=path,
        pinned_ip=public[0],
    )


def _assert_public_ip(value: str) -> None:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError as exc:
        raise InvalidRequest("The model service resolved to an invalid address.") from exc
    if ip.is_multicast or ip.is_reserved or ip.is_loopback or ip.is_link_local or ip.is_private:
        raise InvalidRequest(
            "Custom model URLs must point at a public address.",
            details={"reason": "blocked_ip"},
        )
    for network in _BLOCKED:
        if ip in network:
            raise InvalidRequest(
                "Custom model URLs must point at a public address.",
                details={"reason": "blocked_ip"},
            )


def default_resolve(host: str) -> list[str]:
    try:
        ipaddress.ip_address(host)
        return [host]
    except ValueError:
        pass
    found: list[str] = []
    try:
        for _family, _type, _proto, _canon, sockaddr in socket.getaddrinfo(host, None):
            address = sockaddr[0]
            if address not in found:
                found.append(address)
    except socket.gaierror as exc:
        raise InvalidRequest("Could not resolve the model service hostname.") from exc
    return found


def pinned_httpx_client(resolved: ResolvedUrl):
    """HTTP client that dials the pinned IP and keeps the original Host / SNI.

    The OpenAI SDK would otherwise re-resolve DNS on every request, which is
    the DNS-rebinding window §7.1 ② exists to close.
    """
    import httpcore
    import httpx

    class PinnedBackend(httpcore.SyncBackend):
        def connect_tcp(
            self,
            host: str,
            port: int,
            timeout: float | None = None,
            local_address: str | None = None,
            socket_options: Any = None,
        ):
            # Re-check the stored IP. Do not look the hostname up again.
            assert_public_https(
                resolved.safe_url,
                resolver=lambda _host: [resolved.pinned_ip],
            )
            return super().connect_tcp(
                resolved.pinned_ip,
                resolved.port,
                timeout=timeout,
                local_address=local_address,
                socket_options=socket_options,
            )

    transport = httpx.HTTPTransport(retries=0, verify=True)
    transport._pool.close()
    transport._pool = httpcore.ConnectionPool(
        network_backend=PinnedBackend(),
        retries=0,
    )
    return httpx.Client(
        transport=transport,
        follow_redirects=False,
        timeout=30.0,
        headers={"Host": resolved.host},
    )


AnyResolver = type(default_resolve)
