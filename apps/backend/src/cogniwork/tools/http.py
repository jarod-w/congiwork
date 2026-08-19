"""HTTP transport used by MCP adapters. Injectable so tests never hit a network."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cogniwork.core.errors import UpstreamError
from cogniwork.tools.vault import redact_obj


@dataclass(slots=True)
class HttpResponse:
    status: int
    data: Any
    headers: dict[str, str]


class HttpTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> HttpResponse:
        target = url
        if params:
            target = f"{url}?{urlencode({k: v for k, v in params.items() if v is not None})}"
        body = None
        hdrs = dict(headers or {})
        if json_body is not None:
            body = json.dumps(json_body).encode()
            hdrs.setdefault("Content-Type", "application/json")
        req = Request(target, data=body, headers=hdrs, method=method.upper())
        try:
            with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - URL comes from our adapters
                raw = resp.read()
                parsed: Any = {}
                if raw:
                    try:
                        parsed = json.loads(raw.decode())
                    except json.JSONDecodeError:
                        parsed = {"text": raw.decode(errors="replace")[:4000]}
                return HttpResponse(int(resp.status), parsed, dict(resp.headers.items()))
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:400]
            raise UpstreamError(
                "The connected service returned an error.",
                details={"status": exc.code, "provider_error": detail},
            ) from None
        except URLError as exc:
            raise UpstreamError(
                "The connected service could not be reached.",
                details={"reason": type(exc).__name__},
            ) from None


class StubTransport:
    """In-process fake of the four first-party APIs. Used by tests and oauth_stub."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> HttpResponse:
        self.calls.append(
            redact_obj(
                {
                    "method": method,
                    "url": url,
                    "params": params or {},
                    "json": json_body or {},
                    "has_auth": bool((headers or {}).get("Authorization")),
                }
            )
        )
        if "oauth2.googleapis.com/token" in url or "github.com/login/oauth/access_token" in url:
            return HttpResponse(
                200,
                {
                    "access_token": "cw-canary-access",
                    "refresh_token": "cw-canary-refresh",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "email": "work@example.com",
                    "login": "example",
                },
                {},
            )
        if "api.notion.com/v1/oauth/token" in url:
            return HttpResponse(
                200,
                {
                    "access_token": "cw-canary-access",
                    "workspace_name": "Example workspace",
                    "bot_id": "bot-1",
                },
                {},
            )
        if "gmail.googleapis.com" in url:
            if "/messages/" in url and url.rstrip("/").split("/")[-1] != "messages":
                return HttpResponse(
                    200,
                    {
                        "id": "m1",
                        "snippet": "Quarterly numbers attached",
                        "payload": {"headers": [{"name": "Subject", "value": "Q3"}]},
                    },
                    {},
                )
            return HttpResponse(
                200,
                {"messages": [{"id": "m1"}, {"id": "m2"}], "threads": [{"id": "t1"}]},
                {},
            )
        if "googleapis.com/calendar" in url or "googleapis.com/calendar/v3" in url:
            if "/events/" in url and not url.endswith("/events"):
                return HttpResponse(
                    200,
                    {
                        "id": "e1",
                        "summary": "Standup",
                        "start": {"dateTime": "2026-08-19T09:00:00Z"},
                    },
                    {},
                )
            return HttpResponse(
                200,
                {
                    "items": [
                        {
                            "id": "e1",
                            "summary": "Standup",
                            "start": {"dateTime": "2026-08-19T09:00:00Z"},
                        },
                    ]
                },
                {},
            )
        if "api.notion.com" in url:
            if "/search" in url:
                return HttpResponse(
                    200,
                    {"results": [{"id": "p1", "object": "page", "url": "https://notion.so/p1"}]},
                    {},
                )
            if "/databases/" in url:
                return HttpResponse(200, {"results": [{"id": "row-1"}]}, {})
            return HttpResponse(200, {"id": "p1", "url": "https://notion.so/p1"}, {})
        if "api.github.com" in url:
            if "/search/code" in url:
                return HttpResponse(
                    200,
                    {"total_count": 1, "items": [{"name": "app.py", "path": "src/app.py"}]},
                    {},
                )
            if url.endswith("/issues"):
                return HttpResponse(
                    201,
                    {"number": 12, "html_url": "https://github.com/acme/app/issues/12"},
                    {},
                )
            if "/merge" in url:
                return HttpResponse(200, {"merged": True, "sha": "abc123"}, {})
            return HttpResponse(200, {"login": "example"}, {})
        if "googleapis.com/oauth2/v2/userinfo" in url or "googleapis.com/oauth2/v3/userinfo" in url:
            return HttpResponse(200, {"email": "work@example.com"}, {})
        if "api.github.com/user" in url:
            return HttpResponse(200, {"login": "example"}, {})
        return HttpResponse(200, {}, {})
