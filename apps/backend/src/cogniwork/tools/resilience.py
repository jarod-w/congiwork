"""Connector resilience: timeout, retry, rate limit, circuit breaker (P0-05 §6).

irreversible tools never auto-retry. A timeout after a send is reported as
uncertain rather than retried.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from cogniwork.consent.models import Risk
from cogniwork.core.errors import RateLimited, UpstreamError
from cogniwork.runtime.tools.spec import ToolResult, ToolSpec


@dataclass
class _Breaker:
    failures: int = 0
    opened_at: float = 0.0


@dataclass
class _Bucket:
    tokens: float = 10.0
    updated_at: float = field(default_factory=time.monotonic)


class Resilience:
    def __init__(
        self,
        *,
        max_retries: int = 2,
        breaker_threshold: int = 5,
        breaker_seconds: float = 60.0,
        rate: float = 10.0,
    ) -> None:
        self.max_retries = max_retries
        self.breaker_threshold = breaker_threshold
        self.breaker_seconds = breaker_seconds
        self.rate = rate
        self._breakers: dict[str, _Breaker] = {}
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def is_open(self, provider: str) -> bool:
        with self._lock:
            item = self._breakers.get(provider)
            if item is None or item.opened_at <= 0:
                return False
            if time.monotonic() - item.opened_at >= self.breaker_seconds:
                item.opened_at = 0
                item.failures = 0
                return False
            return True

    def open_providers(self) -> set[str]:
        return {name for name in list(self._breakers) if self.is_open(name)}

    def acquire(self, user_id: str, provider: str) -> None:
        key = f"{user_id}:{provider}"
        with self._lock:
            bucket = self._buckets.setdefault(key, _Bucket())
            now = time.monotonic()
            elapsed = now - bucket.updated_at
            bucket.tokens = min(self.rate, bucket.tokens + elapsed * self.rate)
            bucket.updated_at = now
            if bucket.tokens < 1:
                raise RateLimited("This connection is busy. Try that step again in a moment.")
            bucket.tokens -= 1

    def record_success(self, provider: str) -> None:
        with self._lock:
            item = self._breakers.setdefault(provider, _Breaker())
            item.failures = 0
            item.opened_at = 0

    def record_failure(self, provider: str, *, status: int | None = None) -> None:
        if status is not None and status < 500:
            return
        with self._lock:
            item = self._breakers.setdefault(provider, _Breaker())
            item.failures += 1
            if item.failures >= self.breaker_threshold:
                item.opened_at = time.monotonic()

    def call(
        self,
        spec: ToolSpec,
        invoke: Any,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> ToolResult:
        provider = _provider_of(spec)
        if self.is_open(provider):
            return ToolResult(
                spec.name,
                False,
                f"{provider} is paused after repeated errors. Other tools still work.",
                {"circuit_open": True, "provider": provider},
            )
        user_id = str(context.get("user_id") or "")
        self.acquire(user_id, provider)
        if spec.risk is Risk.IRREVERSIBLE or not spec.retryable:
            attempts = 1
        else:
            attempts = self.max_retries + 1
        last: ToolResult | None = None
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                result = invoke(spec, arguments, context)
            except UpstreamError as exc:
                last_exc = exc
                status = int((exc.details or {}).get("status") or 503)
                self.record_failure(provider, status=status)
                if spec.risk is Risk.IRREVERSIBLE:
                    return ToolResult(
                        spec.name,
                        False,
                        "I am not sure this already happened, so I did not retry. Please check.",
                        {"uncertain": True, "provider": provider},
                    )
                if attempt + 1 >= attempts:
                    break
                time.sleep(0.05 * (2**attempt))
                continue
            except Exception as exc:
                last_exc = exc
                self.record_failure(provider, status=503)
                if spec.risk is Risk.IRREVERSIBLE:
                    return ToolResult(
                        spec.name,
                        False,
                        "I am not sure this already happened, so I did not retry. Please check.",
                        {"uncertain": True, "provider": provider},
                    )
                if attempt + 1 >= attempts:
                    break
                time.sleep(0.05 * (2**attempt))
                continue
            if result.ok:
                self.record_success(provider)
                return result
            last = result
            if spec.risk is Risk.IRREVERSIBLE:
                return result
            self.record_failure(provider, status=503)
            if attempt + 1 >= attempts:
                break
            time.sleep(0.05 * (2**attempt))
        if last is not None:
            return last
        return ToolResult(
            spec.name,
            False,
            "The connected service did not respond.",
            {"error": type(last_exc).__name__ if last_exc else "upstream_error"},
        )


def _provider_of(spec: ToolSpec) -> str:
    if spec.provider == "mcp" and "." in spec.name:
        return spec.name.split(".", 1)[0]
    return spec.provider
