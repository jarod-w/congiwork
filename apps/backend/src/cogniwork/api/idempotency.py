"""POST 创建接口的 Idempotency-Key（00-conventions.md §6）。

缓存 24 小时。同一把 key 配不同请求体视为冲突，而不是静默覆盖。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

from cogniwork.core.errors import Conflict

_TTL_SECONDS = 60 * 60 * 24


def fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def replay(request: Request, body_hash: str) -> JSONResponse | None:
    header = request.headers.get("idempotency-key")
    if not header:
        return None
    cache_key = _cache_key(request, header)
    raw = _load(request, cache_key)
    if raw is None:
        return None
    cached = json.loads(raw)
    if cached["body_hash"] != body_hash:
        raise Conflict("Idempotency-Key was reused with a different request.")
    return JSONResponse(status_code=cached["status"], content=cached["body"])


def remember(request: Request, body_hash: str, status: int, body: dict[str, Any]) -> None:
    header = request.headers.get("idempotency-key")
    if not header:
        return
    cache_key = _cache_key(request, header)
    encoded = json.dumps(
        {"body_hash": body_hash, "status": status, "body": body},
        default=str,
    )
    request.app.state.idempotency[cache_key] = encoded
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        return
    try:
        redis.set(cache_key, encoded, ex=_TTL_SECONDS)
    except RedisError:
        return


def _cache_key(request: Request, header: str) -> str:
    return f"idem:{request.method}:{request.url.path}:{header}"


def _load(request: Request, cache_key: str) -> str | None:
    redis = getattr(request.app.state, "redis", None)
    if redis is not None:
        try:
            value = redis.get(cache_key)
            if value is not None:
                return value
        except RedisError:
            pass
    stored = request.app.state.idempotency.get(cache_key)
    return stored if isinstance(stored, str) else None
