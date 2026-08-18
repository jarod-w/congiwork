"""审计只记「做了什么」，不记「内容是什么」（硬约束 8）。"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from cogniwork.core.clock import now
from cogniwork.core.ids import new_id


def digest_value(value: Any) -> Any:
    """把可能含正文/名单的值收成长度与哈希。事件和 step 表都走这里。"""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        encoded = value.encode()
        return {
            "kind": "string",
            "length": len(value),
            "sha256": hashlib.sha256(encoded).hexdigest()[:16] if len(value) > 24 else None,
        }
    if isinstance(value, bytes):
        return {
            "kind": "bytes",
            "length": len(value),
            "sha256": hashlib.sha256(value).hexdigest()[:16],
        }
    if isinstance(value, list):
        return {"kind": "list", "length": len(value)}
    if isinstance(value, dict):
        return {str(k): digest_value(v) for k, v in value.items()}
    return {"kind": type(value).__name__}


def digest_args(args: dict[str, Any] | None) -> dict[str, Any]:
    if not args:
        return {}
    return {str(k): digest_value(v) for k, v in args.items()}


class InMemoryAuditLog:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def record(
        self,
        *,
        user_id: str,
        task_id: str | None,
        step_id: str | None,
        scope_key: str | None,
        surface: str,
        action: str,
        target_digest: dict[str, Any] | None,
        result: str,
        error_code: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        self.rows.append(
            {
                "id": str(new_id()),
                "user_id": user_id,
                "task_id": task_id,
                "step_id": step_id,
                "scope_key": scope_key,
                "surface": _audit_surface(surface),
                "action": action,
                "target_digest": target_digest,
                "result": result,
                "error_code": error_code,
                "duration_ms": duration_ms,
                "created_at": now(),
            }
        )

    def clear(self) -> None:
        self.rows.clear()


class PostgresAuditLog:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    def record(
        self,
        *,
        user_id: str,
        task_id: str | None,
        step_id: str | None,
        scope_key: str | None,
        surface: str,
        action: str,
        target_digest: dict[str, Any] | None,
        result: str,
        error_code: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        from psycopg.types.json import Json

        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO execution_audit (
                    id, user_id, task_id, step_id, scope_key, surface,
                    action, target_digest, result, error_code, duration_ms, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    new_id(),
                    UUID(user_id),
                    UUID(task_id) if task_id else None,
                    UUID(step_id) if step_id else None,
                    scope_key,
                    _audit_surface(surface),
                    action,
                    Json(target_digest) if target_digest is not None else None,
                    result,
                    error_code,
                    duration_ms,
                    now(),
                ),
            )

    def clear(self) -> None:
        with self._pool.connection() as conn:
            conn.execute("TRUNCATE execution_audit")


def _audit_surface(surface: str) -> str:
    # execution_audit 的 CHECK 不含 api；API 面按 web 记。
    if surface in {"web", "desktop", "browser_ext"}:
        return surface
    return "web"
