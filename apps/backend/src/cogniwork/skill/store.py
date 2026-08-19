"""Skill persistence. InMemory for tests; Postgres follows 0007_skill.sql."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Json

from .models import CustomLlmProvider, ProductEvent, Skill, SkillSource, SkillStatus, SkillVersion


def _skill_from_row(row: dict[str, Any]) -> Skill:
    return Skill(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        description=row["description"],
        trigger=dict(row["trigger"] or {}),
        input_schema=dict(row["input_schema"] or {}),
        workflow=list(row["workflow"] or []),
        tools=list(row.get("tools") or []),
        required_scopes=list(row.get("required_scopes") or []),
        source=SkillSource(row["source"]),
        source_ref=row.get("source_ref"),
        version=int(row["version"]),
        status=SkillStatus(row["status"]),
        run_count=int(row.get("run_count") or 0),
        success_count=int(row.get("success_count") or 0),
        last_run_at=row.get("last_run_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _version_from_row(row: dict[str, Any]) -> SkillVersion:
    return SkillVersion(
        skill_id=row["skill_id"],
        version=int(row["version"]),
        snapshot=dict(row["snapshot"] or {}),
        changed_by=row["changed_by"],
        change_note=row.get("change_note"),
        created_at=row["created_at"],
    )


def _provider_from_row(row: dict[str, Any]) -> CustomLlmProvider:
    return CustomLlmProvider(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        base_url=row["base_url"],
        model=row["model"],
        ciphertext=bytes(row["ciphertext"]),
        dek_wrapped=bytes(row["dek_wrapped"]),
        key_version=int(row["key_version"]),
        capabilities=dict(row.get("capabilities") or {}),
        unit_cost_usd=float(row["unit_cost_usd"]) if row.get("unit_cost_usd") is not None else None,
        status=row["status"],
        last_probed_at=row.get("last_probed_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class InMemorySkillStore:
    def __init__(self) -> None:
        self.skills: dict[UUID, Skill] = {}
        self.versions: dict[tuple[UUID, int], SkillVersion] = {}
        self.providers: dict[UUID, CustomLlmProvider] = {}
        self.events: list[ProductEvent] = []
        self.usage: dict[tuple[UUID, str], dict[str, Any]] = {}

    def upsert_skill(self, skill: Skill) -> Skill:
        self.skills[skill.id] = skill
        return skill

    def get_skill(self, user_id: UUID, skill_id: UUID) -> Skill | None:
        item = self.skills.get(skill_id)
        if item is None or item.user_id != user_id:
            return None
        return item

    def list_skills(
        self,
        user_id: UUID,
        *,
        query: str | None = None,
        status: SkillStatus | None = None,
        include_archived: bool = False,
    ) -> list[Skill]:
        found = [item for item in self.skills.values() if item.user_id == user_id]
        if not include_archived:
            found = [item for item in found if item.status is not SkillStatus.ARCHIVED]
        if status is not None:
            found = [item for item in found if item.status is status]
        if query:
            needle = query.lower()
            found = [
                item
                for item in found
                if needle in item.name.lower() or needle in item.description.lower()
            ]
        found.sort(key=lambda item: item.updated_at, reverse=True)
        return found

    def delete_skill(self, user_id: UUID, skill_id: UUID) -> bool:
        item = self.get_skill(user_id, skill_id)
        if item is None:
            return False
        self.skills.pop(skill_id, None)
        gone = [key for key in self.versions if key[0] == skill_id]
        for key in gone:
            self.versions.pop(key, None)
        return True

    def delete_for_user(self, user_id: UUID) -> int:
        ids = [item.id for item in self.skills.values() if item.user_id == user_id]
        for skill_id in ids:
            self.delete_skill(user_id, skill_id)
        gone = [key for key, item in self.providers.items() if item.user_id == user_id]
        for key in gone:
            self.providers.pop(key, None)
        self.events = [row for row in self.events if row.user_id != user_id]
        self.usage = {key: val for key, val in self.usage.items() if key[0] != user_id}
        return len(ids)

    def add_version(self, version: SkillVersion) -> SkillVersion:
        self.versions[(version.skill_id, version.version)] = version
        return version

    def list_versions(self, skill_id: UUID) -> list[SkillVersion]:
        found = [item for key, item in self.versions.items() if key[0] == skill_id]
        found.sort(key=lambda item: item.version, reverse=True)
        return found

    def get_version(self, skill_id: UUID, version: int) -> SkillVersion | None:
        return self.versions.get((skill_id, version))

    def upsert_provider(self, provider: CustomLlmProvider) -> CustomLlmProvider:
        self.providers[provider.id] = provider
        return provider

    def get_provider(self, user_id: UUID) -> CustomLlmProvider | None:
        found = [
            item
            for item in self.providers.values()
            if item.user_id == user_id and item.status != "disabled"
        ]
        found.sort(key=lambda item: item.updated_at, reverse=True)
        return found[0] if found else None

    def get_provider_by_id(self, user_id: UUID, provider_id: UUID) -> CustomLlmProvider | None:
        item = self.providers.get(provider_id)
        if item is None or item.user_id != user_id:
            return None
        return item

    def add_event(self, event: ProductEvent) -> ProductEvent:
        self.events.append(event)
        return event

    def list_events(self, user_id: UUID, name: str | None = None) -> list[ProductEvent]:
        found = [row for row in self.events if row.user_id == user_id]
        if name:
            found = [row for row in found if row.name == name]
        return found

    def add_usage(
        self, user_id: UUID, day: str, cost_usd: float, token_in: int, token_out: int
    ) -> None:
        key = (user_id, day)
        current = self.usage.get(key) or {"cost_usd": 0.0, "token_in": 0, "token_out": 0}
        current["cost_usd"] += cost_usd
        current["token_in"] += token_in
        current["token_out"] += token_out
        self.usage[key] = current

    def get_usage(self, user_id: UUID, day: str) -> dict[str, Any]:
        empty = {"cost_usd": 0.0, "token_in": 0, "token_out": 0}
        return dict(self.usage.get((user_id, day)) or empty)

    def clear(self) -> None:
        self.skills.clear()
        self.versions.clear()
        self.providers.clear()
        self.events.clear()
        self.usage.clear()


class PostgresSkillStore:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    def upsert_skill(self, skill: Skill) -> Skill:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO skill (
                    id, user_id, name, description, trigger, input_schema, workflow,
                    tools, required_scopes, source, source_ref, version, status,
                    run_count, success_count, last_run_at, created_at, updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    trigger = EXCLUDED.trigger,
                    input_schema = EXCLUDED.input_schema,
                    workflow = EXCLUDED.workflow,
                    tools = EXCLUDED.tools,
                    required_scopes = EXCLUDED.required_scopes,
                    source = EXCLUDED.source,
                    source_ref = EXCLUDED.source_ref,
                    version = EXCLUDED.version,
                    status = EXCLUDED.status,
                    run_count = EXCLUDED.run_count,
                    success_count = EXCLUDED.success_count,
                    last_run_at = EXCLUDED.last_run_at,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    skill.id,
                    skill.user_id,
                    skill.name,
                    skill.description,
                    Json(skill.trigger),
                    Json(skill.input_schema),
                    Json(skill.workflow),
                    skill.tools,
                    skill.required_scopes,
                    skill.source.value,
                    Json(skill.source_ref) if skill.source_ref is not None else None,
                    skill.version,
                    skill.status.value,
                    skill.run_count,
                    skill.success_count,
                    skill.last_run_at,
                    skill.created_at,
                    skill.updated_at,
                ),
            )
        return skill

    def get_skill(self, user_id: UUID, skill_id: UUID) -> Skill | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM skill WHERE id = %s AND user_id = %s",
                (skill_id, user_id),
            ).fetchone()
        return _skill_from_row(row) if row else None

    def list_skills(
        self,
        user_id: UUID,
        *,
        query: str | None = None,
        status: SkillStatus | None = None,
        include_archived: bool = False,
    ) -> list[Skill]:
        sql = "SELECT * FROM skill WHERE user_id = %s"
        params: list[Any] = [user_id]
        if not include_archived:
            sql += " AND status <> 'archived'"
        if status is not None:
            sql += " AND status = %s"
            params.append(status.value)
        if query:
            sql += " AND (name ILIKE %s OR description ILIKE %s)"
            like = f"%{query}%"
            params.extend([like, like])
        sql += " ORDER BY updated_at DESC"
        with self._pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_skill_from_row(row) for row in rows]

    def delete_skill(self, user_id: UUID, skill_id: UUID) -> bool:
        with self._pool.connection() as conn:
            row = conn.execute(
                "DELETE FROM skill WHERE id = %s AND user_id = %s RETURNING id",
                (skill_id, user_id),
            ).fetchone()
        return row is not None

    def delete_for_user(self, user_id: UUID) -> int:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                WITH gone AS (DELETE FROM skill WHERE user_id = %s RETURNING id)
                SELECT count(*) AS n FROM gone
                """,
                (user_id,),
            ).fetchone()
            conn.execute("DELETE FROM custom_llm_provider WHERE user_id = %s", (user_id,))
            conn.execute("DELETE FROM product_event WHERE user_id = %s", (user_id,))
            conn.execute("DELETE FROM daily_llm_usage WHERE user_id = %s", (user_id,))
        return int(row["n"]) if row else 0

    def add_version(self, version: SkillVersion) -> SkillVersion:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO skill_version (
                    skill_id, version, snapshot, changed_by, change_note, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (skill_id, version) DO UPDATE SET snapshot = EXCLUDED.snapshot
                """,
                (
                    version.skill_id,
                    version.version,
                    Json(version.snapshot),
                    version.changed_by,
                    version.change_note,
                    version.created_at,
                ),
            )
        return version

    def list_versions(self, skill_id: UUID) -> list[SkillVersion]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM skill_version WHERE skill_id = %s ORDER BY version DESC",
                (skill_id,),
            ).fetchall()
        return [_version_from_row(row) for row in rows]

    def get_version(self, skill_id: UUID, version: int) -> SkillVersion | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM skill_version WHERE skill_id = %s AND version = %s",
                (skill_id, version),
            ).fetchone()
        return _version_from_row(row) if row else None

    def upsert_provider(self, provider: CustomLlmProvider) -> CustomLlmProvider:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO custom_llm_provider (
                    id, user_id, name, base_url, model, ciphertext, dek_wrapped,
                    key_version, capabilities, unit_cost_usd, status,
                    last_probed_at, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    base_url = EXCLUDED.base_url,
                    model = EXCLUDED.model,
                    ciphertext = EXCLUDED.ciphertext,
                    dek_wrapped = EXCLUDED.dek_wrapped,
                    key_version = EXCLUDED.key_version,
                    capabilities = EXCLUDED.capabilities,
                    unit_cost_usd = EXCLUDED.unit_cost_usd,
                    status = EXCLUDED.status,
                    last_probed_at = EXCLUDED.last_probed_at,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    provider.id,
                    provider.user_id,
                    provider.name,
                    provider.base_url,
                    provider.model,
                    provider.ciphertext,
                    provider.dek_wrapped,
                    provider.key_version,
                    Json(provider.capabilities),
                    provider.unit_cost_usd,
                    provider.status,
                    provider.last_probed_at,
                    provider.created_at,
                    provider.updated_at,
                ),
            )
        return provider

    def get_provider(self, user_id: UUID) -> CustomLlmProvider | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM custom_llm_provider
                WHERE user_id = %s AND status <> 'disabled'
                ORDER BY updated_at DESC LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        return _provider_from_row(row) if row else None

    def get_provider_by_id(self, user_id: UUID, provider_id: UUID) -> CustomLlmProvider | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM custom_llm_provider WHERE id = %s AND user_id = %s",
                (provider_id, user_id),
            ).fetchone()
        return _provider_from_row(row) if row else None

    def add_event(self, event: ProductEvent) -> ProductEvent:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO product_event (id, user_id, name, payload, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (event.id, event.user_id, event.name, Json(event.payload), event.created_at),
            )
        return event

    def list_events(self, user_id: UUID, name: str | None = None) -> list[ProductEvent]:
        sql = "SELECT * FROM product_event WHERE user_id = %s"
        params: list[Any] = [user_id]
        if name:
            sql += " AND name = %s"
            params.append(name)
        sql += " ORDER BY created_at DESC"
        with self._pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            ProductEvent(
                id=row["id"],
                user_id=row["user_id"],
                name=row["name"],
                payload=dict(row.get("payload") or {}),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def add_usage(
        self, user_id: UUID, day: str, cost_usd: float, token_in: int, token_out: int
    ) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO daily_llm_usage (user_id, day, cost_usd, token_in, token_out)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id, day) DO UPDATE SET
                    cost_usd = daily_llm_usage.cost_usd + EXCLUDED.cost_usd,
                    token_in = daily_llm_usage.token_in + EXCLUDED.token_in,
                    token_out = daily_llm_usage.token_out + EXCLUDED.token_out
                """,
                (user_id, day, cost_usd, token_in, token_out),
            )

    def get_usage(self, user_id: UUID, day: str) -> dict[str, Any]:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM daily_llm_usage WHERE user_id = %s AND day = %s",
                (user_id, day),
            ).fetchone()
        if row is None:
            return {"cost_usd": 0.0, "token_in": 0, "token_out": 0}
        return {
            "cost_usd": float(row["cost_usd"] or 0),
            "token_in": int(row["token_in"] or 0),
            "token_out": int(row["token_out"] or 0),
        }
