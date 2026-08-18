"""ConsentStore 实现。

运行时读路径（P0-07 §4）：Redis `consent:{user_id}` hash 优先，
未命中回落 `consent_current` 物化视图。写路径是 append-only：
撤销不是 UPDATE/DELETE，而是再插一条 action='revoked'。

InMemoryConsentStore 给单测与无基础设施的本地启动。
生产用 PostgresConsentStore。
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from psycopg.types.json import Json
from redis import Redis
from redis.exceptions import RedisError

from cogniwork.core.clock import now
from cogniwork.core.ids import new_id

from .models import ConsentAction, ConsentState

logger = logging.getLogger("cogniwork.consent.store")

_LOADED = "_loaded"
_CACHE_TTL_SECONDS = 3600


class InMemoryConsentStore:
    """内存实现 —— 用于测试与本地开发，不用于生产。"""

    def __init__(self, states: dict[tuple[str, str], ConsentState] | None = None) -> None:
        self._states = dict(states or {})
        self._log: list[dict[str, Any]] = []

    def current(self, user_id: str, scope_key: str) -> ConsentState | None:
        return self._states.get((user_id, scope_key))

    def set(self, state: ConsentState) -> None:
        self._states[(state.user_id, state.scope_key)] = state

    def append(
        self,
        *,
        user_id: str,
        scope_key: str,
        action: ConsentAction,
        always_allow: bool,
        surface: str,
        consent_text_version: str,
        device_info: dict[str, Any] | None = None,
        ip_hash: str | None = None,
    ) -> None:
        self._log.append(
            {
                "id": str(new_id()),
                "user_id": user_id,
                "scope_key": scope_key,
                "action": action,
                "always_allow": always_allow,
                "surface": surface,
                "consent_text_version": consent_text_version,
                "device_info": device_info,
                "ip_hash": ip_hash,
                "created_at": now(),
            }
        )
        self._states[(user_id, scope_key)] = ConsentState(
            user_id, scope_key, action, always_allow
        )

    def clear(self) -> None:
        self._states.clear()
        self._log.clear()


class PostgresConsentStore:
    """Redis 优先、Postgres 回落的授权状态存储。"""

    def __init__(self, pool: Any, redis: Redis | None = None) -> None:
        self._pool = pool
        self._redis = redis

    def current(self, user_id: str, scope_key: str) -> ConsentState | None:
        cached = self._from_redis(user_id, scope_key)
        if cached is not None or self._redis_has_user(user_id):
            return cached
        self._hydrate(user_id)
        cached = self._from_redis(user_id, scope_key)
        if cached is not None or self._redis_has_user(user_id):
            return cached
        return self._from_postgres(user_id, scope_key)

    def append(
        self,
        *,
        user_id: str,
        scope_key: str,
        action: ConsentAction,
        always_allow: bool,
        surface: str,
        consent_text_version: str,
        device_info: dict[str, Any] | None = None,
        ip_hash: str | None = None,
    ) -> None:
        record_id = new_id()
        created_at = now()
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO consent_record (
                    id, user_id, scope_key, action, always_allow,
                    surface, consent_text_version, device_info, ip_hash, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    record_id,
                    UUID(user_id),
                    scope_key,
                    action.value,
                    always_allow,
                    surface,
                    consent_text_version,
                    Json(device_info) if device_info is not None else None,
                    ip_hash,
                    created_at,
                ),
            )
            # 与 INSERT 同一事务刷新物化视图，避免 Redis 未命中时读到上一拍。
            conn.execute("REFRESH MATERIALIZED VIEW consent_current")
        self._invalidate(user_id)

    def clear(self) -> None:
        """测试用。生产路径没有「清空授权」这种操作。"""
        with self._pool.connection() as conn:
            conn.execute("TRUNCATE consent_record")
            conn.execute("REFRESH MATERIALIZED VIEW consent_current")
        if self._redis is not None:
            try:
                for key in self._redis.scan_iter("consent:*"):
                    self._redis.delete(key)
            except RedisError:
                logger.warning("failed to flush consent cache during test wipe")

    def _redis_has_user(self, user_id: str) -> bool:
        if self._redis is None:
            return False
        try:
            return bool(self._redis.hexists(f"consent:{user_id}", _LOADED))
        except RedisError:
            return False

    def _from_redis(self, user_id: str, scope_key: str) -> ConsentState | None:
        if self._redis is None:
            return None
        try:
            raw = self._redis.hget(f"consent:{user_id}", scope_key)
        except RedisError:
            logger.warning("consent redis read failed; falling back to postgres")
            return None
        if not raw:
            return None
        payload = json.loads(raw)
        return ConsentState(
            user_id=user_id,
            scope_key=scope_key,
            action=ConsentAction(payload["action"]),
            always_allow=bool(payload["always_allow"]),
        )

    def _hydrate(self, user_id: str) -> None:
        rows = self._load_current_rows(user_id)
        if self._redis is None:
            return
        mapping = {_LOADED: "1"}
        for row in rows:
            mapping[row["scope_key"]] = json.dumps(
                {"action": row["action"], "always_allow": row["always_allow"]}
            )
        try:
            key = f"consent:{user_id}"
            pipe = self._redis.pipeline()
            pipe.delete(key)
            pipe.hset(key, mapping=mapping)
            pipe.expire(key, _CACHE_TTL_SECONDS)
            pipe.execute()
        except RedisError:
            logger.warning("consent redis hydrate failed")

    def _from_postgres(self, user_id: str, scope_key: str) -> ConsentState | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT action, always_allow
                FROM consent_current
                WHERE user_id = %s AND scope_key = %s
                """,
                (UUID(user_id), scope_key),
            ).fetchone()
        if row is None:
            return None
        return ConsentState(
            user_id=user_id,
            scope_key=scope_key,
            action=ConsentAction(row["action"]),
            always_allow=bool(row["always_allow"]),
        )

    def _load_current_rows(self, user_id: str) -> list[dict[str, Any]]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT scope_key, action, always_allow
                FROM consent_current
                WHERE user_id = %s
                """,
                (UUID(user_id),),
            ).fetchall()
        return list(rows)

    def _invalidate(self, user_id: str) -> None:
        if self._redis is None:
            return
        try:
            self._redis.delete(f"consent:{user_id}")
        except RedisError:
            logger.warning("consent redis invalidation failed for user %s", user_id)
