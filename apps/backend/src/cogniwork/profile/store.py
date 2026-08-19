"""Profile persistence. InMemory for tests; Postgres follows 0005_profile.sql."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Json

from .models import (
    FieldSource,
    FieldStatus,
    InterviewSession,
    InterviewStatus,
    Profile,
    ProfileField,
)


def _profile_from_row(row: dict[str, Any]) -> Profile:
    return Profile(
        id=row["id"],
        user_id=row["user_id"],
        org_id=row.get("org_id"),
        version=int(row["version"]),
        completed=bool(row["completed"]),
        archived_at=row.get("archived_at"),
        archive_reason=row.get("archive_reason"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _field_from_row(row: dict[str, Any]) -> ProfileField:
    return ProfileField(
        id=row["id"],
        profile_id=row["profile_id"],
        user_id=row["user_id"],
        key=row["key"],
        value=row["value"],
        source=FieldSource(row["source"]),
        confidence=float(row["confidence"]),
        status=FieldStatus(row["status"]),
        evidence=row.get("evidence"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _session_from_row(row: dict[str, Any]) -> InterviewSession:
    return InterviewSession(
        id=row["id"],
        user_id=row["user_id"],
        profile_id=row["profile_id"],
        status=InterviewStatus(row["status"]),
        round=int(row["round"]),
        question_key=row.get("question_key"),
        answers=dict(row.get("answers") or {}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class InMemoryProfileStore:
    def __init__(self) -> None:
        self.profiles: dict[UUID, Profile] = {}
        self.fields: dict[UUID, ProfileField] = {}
        self.sessions: dict[UUID, InterviewSession] = {}

    def upsert_profile(self, profile: Profile) -> Profile:
        self.profiles[profile.id] = profile
        return profile

    def get_profile(self, user_id: UUID, profile_id: UUID) -> Profile | None:
        item = self.profiles.get(profile_id)
        if item is None or item.user_id != user_id:
            return None
        return item

    def active_profile(self, user_id: UUID) -> Profile | None:
        found = [
            item
            for item in self.profiles.values()
            if item.user_id == user_id and item.archived_at is None
        ]
        found.sort(key=lambda item: item.updated_at, reverse=True)
        return found[0] if found else None

    def list_profiles(self, user_id: UUID, *, include_archived: bool = True) -> list[Profile]:
        found = [item for item in self.profiles.values() if item.user_id == user_id]
        if not include_archived:
            found = [item for item in found if item.archived_at is None]
        found.sort(key=lambda item: item.created_at, reverse=True)
        return found

    def upsert_field(self, item: ProfileField) -> ProfileField:
        self.fields[item.id] = item
        return item

    def get_field(self, user_id: UUID, field_id: UUID) -> ProfileField | None:
        item = self.fields.get(field_id)
        if item is None or item.user_id != user_id:
            return None
        return item

    def field_by_key(
        self, profile_id: UUID, key: str, status: FieldStatus | None = None
    ) -> ProfileField | None:
        found = [
            item
            for item in self.fields.values()
            if item.profile_id == profile_id and item.key == key
        ]
        if status is not None:
            found = [item for item in found if item.status is status]
        found.sort(key=lambda item: item.updated_at, reverse=True)
        return found[0] if found else None

    def list_fields(
        self,
        profile_id: UUID,
        *,
        status: FieldStatus | None = None,
    ) -> list[ProfileField]:
        found = [item for item in self.fields.values() if item.profile_id == profile_id]
        if status is not None:
            found = [item for item in found if item.status is status]
        found.sort(key=lambda item: item.updated_at, reverse=True)
        return found

    def delete_field(self, user_id: UUID, field_id: UUID) -> bool:
        item = self.get_field(user_id, field_id)
        if item is None:
            return False
        del self.fields[field_id]
        return True

    def delete_fields_for_profile(self, profile_id: UUID) -> int:
        ids = [item.id for item in self.fields.values() if item.profile_id == profile_id]
        for field_id in ids:
            del self.fields[field_id]
        return len(ids)

    def delete_profiles_for_user(self, user_id: UUID) -> int:
        pids = [item.id for item in self.profiles.values() if item.user_id == user_id]
        for pid in pids:
            self.delete_fields_for_profile(pid)
            gone = [sid for sid, row in self.sessions.items() if row.profile_id == pid]
            for sid in gone:
                del self.sessions[sid]
            del self.profiles[pid]
        return len(pids)

    def upsert_session(self, session: InterviewSession) -> InterviewSession:
        self.sessions[session.id] = session
        return session

    def open_session(self, profile_id: UUID) -> InterviewSession | None:
        open_states = {
            InterviewStatus.NOT_STARTED,
            InterviewStatus.IN_PROGRESS,
            InterviewStatus.AWAITING_SUMMARY,
        }
        found = [
            item
            for item in self.sessions.values()
            if item.profile_id == profile_id and item.status in open_states
        ]
        found.sort(key=lambda item: item.updated_at, reverse=True)
        return found[0] if found else None

    def latest_session(self, profile_id: UUID) -> InterviewSession | None:
        found = [item for item in self.sessions.values() if item.profile_id == profile_id]
        found.sort(key=lambda item: item.updated_at, reverse=True)
        return found[0] if found else None

    def clear(self) -> None:
        self.profiles.clear()
        self.fields.clear()
        self.sessions.clear()


class PostgresProfileStore:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    def upsert_profile(self, profile: Profile) -> Profile:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO profile (
                    id, user_id, org_id, version, completed, archived_at,
                    archive_reason, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    version = EXCLUDED.version,
                    completed = EXCLUDED.completed,
                    archived_at = EXCLUDED.archived_at,
                    archive_reason = EXCLUDED.archive_reason,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    profile.id,
                    profile.user_id,
                    profile.org_id,
                    profile.version,
                    profile.completed,
                    profile.archived_at,
                    profile.archive_reason,
                    profile.created_at,
                    profile.updated_at,
                ),
            )
        return profile

    def get_profile(self, user_id: UUID, profile_id: UUID) -> Profile | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM profile WHERE id = %s AND user_id = %s",
                (profile_id, user_id),
            ).fetchone()
        return _profile_from_row(row) if row else None

    def active_profile(self, user_id: UUID) -> Profile | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM profile
                WHERE user_id = %s AND archived_at IS NULL
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        return _profile_from_row(row) if row else None

    def list_profiles(self, user_id: UUID, *, include_archived: bool = True) -> list[Profile]:
        sql = "SELECT * FROM profile WHERE user_id = %s"
        if not include_archived:
            sql += " AND archived_at IS NULL"
        sql += " ORDER BY created_at DESC"
        with self._pool.connection() as conn:
            rows = conn.execute(sql, (user_id,)).fetchall()
        return [_profile_from_row(row) for row in rows]

    def upsert_field(self, item: ProfileField) -> ProfileField:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO profile_field (
                    id, profile_id, user_id, key, value, source, confidence,
                    status, evidence, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    value = EXCLUDED.value,
                    source = EXCLUDED.source,
                    confidence = EXCLUDED.confidence,
                    status = EXCLUDED.status,
                    evidence = EXCLUDED.evidence,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    item.id,
                    item.profile_id,
                    item.user_id,
                    item.key,
                    Json(item.value),
                    item.source.value,
                    item.confidence,
                    item.status.value,
                    Json(item.evidence) if item.evidence is not None else None,
                    item.created_at,
                    item.updated_at,
                ),
            )
        return item

    def get_field(self, user_id: UUID, field_id: UUID) -> ProfileField | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM profile_field WHERE id = %s AND user_id = %s",
                (field_id, user_id),
            ).fetchone()
        return _field_from_row(row) if row else None

    def field_by_key(
        self, profile_id: UUID, key: str, status: FieldStatus | None = None
    ) -> ProfileField | None:
        sql = "SELECT * FROM profile_field WHERE profile_id = %s AND key = %s"
        params: list[Any] = [profile_id, key]
        if status is not None:
            sql += " AND status = %s"
            params.append(status.value)
        sql += " ORDER BY updated_at DESC LIMIT 1"
        with self._pool.connection() as conn:
            row = conn.execute(sql, params).fetchone()
        return _field_from_row(row) if row else None

    def list_fields(
        self,
        profile_id: UUID,
        *,
        status: FieldStatus | None = None,
    ) -> list[ProfileField]:
        sql = "SELECT * FROM profile_field WHERE profile_id = %s"
        params: list[Any] = [profile_id]
        if status is not None:
            sql += " AND status = %s"
            params.append(status.value)
        sql += " ORDER BY updated_at DESC"
        with self._pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_field_from_row(row) for row in rows]

    def delete_field(self, user_id: UUID, field_id: UUID) -> bool:
        with self._pool.connection() as conn:
            row = conn.execute(
                "DELETE FROM profile_field WHERE id = %s AND user_id = %s RETURNING id",
                (field_id, user_id),
            ).fetchone()
        return row is not None

    def delete_fields_for_profile(self, profile_id: UUID) -> int:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                WITH gone AS (
                    DELETE FROM profile_field WHERE profile_id = %s RETURNING id
                )
                SELECT count(*) AS n FROM gone
                """,
                (profile_id,),
            ).fetchone()
        return int(row["n"]) if row else 0

    def delete_profiles_for_user(self, user_id: UUID) -> int:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                WITH gone AS (
                    DELETE FROM profile WHERE user_id = %s RETURNING id
                )
                SELECT count(*) AS n FROM gone
                """,
                (user_id,),
            ).fetchone()
        return int(row["n"]) if row else 0

    def upsert_session(self, session: InterviewSession) -> InterviewSession:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO interview_session (
                    id, user_id, profile_id, status, round, question_key,
                    answers, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    round = EXCLUDED.round,
                    question_key = EXCLUDED.question_key,
                    answers = EXCLUDED.answers,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    session.id,
                    session.user_id,
                    session.profile_id,
                    session.status.value,
                    session.round,
                    session.question_key,
                    Json(session.answers),
                    session.created_at,
                    session.updated_at,
                ),
            )
        return session

    def open_session(self, profile_id: UUID) -> InterviewSession | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM interview_session
                WHERE profile_id = %s
                  AND status IN ('not_started', 'in_progress', 'awaiting_summary')
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (profile_id,),
            ).fetchone()
        return _session_from_row(row) if row else None

    def latest_session(self, profile_id: UUID) -> InterviewSession | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM interview_session
                WHERE profile_id = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (profile_id,),
            ).fetchone()
        return _session_from_row(row) if row else None

    def clear(self) -> None:
        with self._pool.connection() as conn:
            conn.execute("TRUNCATE profile CASCADE")
            conn.execute("TRUNCATE interview_session")
