"""用户设置。B6：任务历史自动清理开关必须出现在界面上，默认关闭。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from cogniwork.core.clock import now
from cogniwork.core.errors import InvalidRequest


@dataclass(slots=True)
class UserSettings:
    user_id: UUID
    episodic_auto_cleanup: bool
    episodic_retention_months: int
    created_at: datetime
    updated_at: datetime


class InMemorySettingsStore:
    def __init__(self) -> None:
        self._rows: dict[UUID, UserSettings] = {}

    def get(self, user_id: UUID) -> UserSettings:
        existing = self._rows.get(user_id)
        if existing is not None:
            return existing
        created = now()
        settings = UserSettings(user_id, False, 12, created, created)
        self._rows[user_id] = settings
        return settings

    def save(self, settings: UserSettings) -> UserSettings:
        self._rows[settings.user_id] = settings
        return settings

    def delete(self, user_id: UUID) -> None:
        self._rows.pop(user_id, None)

    def clear(self) -> None:
        self._rows.clear()


class PostgresSettingsStore:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    def get(self, user_id: UUID) -> UserSettings:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM user_settings WHERE user_id = %s",
                (user_id,),
            ).fetchone()
        if row:
            return _from_row(row)
        created = now()
        settings = UserSettings(user_id, False, 12, created, created)
        return self.save(settings)

    def save(self, settings: UserSettings) -> UserSettings:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO user_settings (
                    user_id, episodic_auto_cleanup, episodic_retention_months,
                    created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    episodic_auto_cleanup = EXCLUDED.episodic_auto_cleanup,
                    episodic_retention_months = EXCLUDED.episodic_retention_months,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    settings.user_id,
                    settings.episodic_auto_cleanup,
                    settings.episodic_retention_months,
                    settings.created_at,
                    settings.updated_at,
                ),
            )
        return settings

    def delete(self, user_id: UUID) -> None:
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM user_settings WHERE user_id = %s", (user_id,))

    def clear(self) -> None:
        with self._pool.connection() as conn:
            conn.execute("TRUNCATE user_settings")


def update_settings(
    store: Any,
    user_id: UUID,
    *,
    episodic_auto_cleanup: bool | None = None,
    episodic_retention_months: int | None = None,
) -> UserSettings:
    settings = store.get(user_id)
    if episodic_auto_cleanup is not None:
        settings.episodic_auto_cleanup = episodic_auto_cleanup
    if episodic_retention_months is not None:
        if not 1 <= episodic_retention_months <= 120:
            raise InvalidRequest("Retention months must be between 1 and 120.")
        settings.episodic_retention_months = episodic_retention_months
    settings.updated_at = now()
    return store.save(settings)


def settings_out(settings: UserSettings) -> dict[str, Any]:
    return {
        "episodic_auto_cleanup": settings.episodic_auto_cleanup,
        "episodic_retention_months": settings.episodic_retention_months,
        "updated_at": settings.updated_at.isoformat(),
    }


def _from_row(row: dict[str, Any]) -> UserSettings:
    return UserSettings(
        user_id=row["user_id"],
        episodic_auto_cleanup=bool(row["episodic_auto_cleanup"]),
        episodic_retention_months=int(row["episodic_retention_months"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
