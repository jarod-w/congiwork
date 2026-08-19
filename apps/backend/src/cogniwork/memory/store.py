"""Memory 持久化。InMemory 给单测；Postgres 走 0004_memory.sql。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Json

from .models import (
    EpisodeOutcome,
    EpisodicRecord,
    MemoryItem,
    MemoryStatus,
    MemoryType,
    SourceType,
)


def _item_from_row(row: dict[str, Any]) -> MemoryItem:
    embedding = row.get("embedding")
    if embedding is not None:
        embedding = [float(v) for v in embedding]
    return MemoryItem(
        id=row["id"],
        user_id=row["user_id"],
        type=MemoryType(row["type"]),
        subtype=row.get("subtype"),
        content=row["content"],
        summary=row.get("summary"),
        embedding=embedding,
        embed_model=row.get("embed_model"),
        importance=int(row["importance"]),
        confidence=float(row["confidence"]),
        source_type=SourceType(row["source_type"]),
        source_ref=row.get("source_ref"),
        scope_key=row.get("scope_key"),
        status=MemoryStatus(row["status"]),
        superseded_by=row.get("superseded_by"),
        conflict_with=row.get("conflict_with"),
        valid_from=row["valid_from"],
        valid_to=row.get("valid_to"),
        last_used_at=row.get("last_used_at"),
        use_count=int(row["use_count"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _episode_from_row(row: dict[str, Any]) -> EpisodicRecord:
    return EpisodicRecord(
        id=row["id"],
        memory_id=row["memory_id"],
        user_id=row["user_id"],
        task_id=row["task_id"],
        title=row["title"],
        intent=row.get("intent"),
        tools_used=list(row.get("tools_used") or []),
        skill_id=row.get("skill_id"),
        outcome=EpisodeOutcome(row["outcome"]),
        decisions=list(row.get("decisions") or []),
        user_edits=list(row.get("user_edits") or []),
        duration_ms=row.get("duration_ms"),
        started_at=row["started_at"],
        ended_at=row.get("ended_at"),
    )


class InMemoryMemoryStore:
    def __init__(self) -> None:
        self.items: dict[UUID, MemoryItem] = {}
        self.episodes: dict[UUID, EpisodicRecord] = {}

    def upsert(self, item: MemoryItem) -> MemoryItem:
        self.items[item.id] = item
        return item

    def get(self, user_id: UUID, memory_id: UUID) -> MemoryItem | None:
        item = self.items.get(memory_id)
        if item is None or item.user_id != user_id:
            return None
        return item

    def list(
        self,
        user_id: UUID,
        *,
        type: MemoryType | None = None,
        status: MemoryStatus | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryItem]:
        found = [item for item in self.items.values() if item.user_id == user_id]
        if type is not None:
            found = [item for item in found if item.type is type]
        if status is not None:
            found = [item for item in found if item.status is status]
        if query:
            needle = query.lower()
            found = [
                item
                for item in found
                if needle in item.content.lower()
                or (item.summary and needle in item.summary.lower())
            ]
        found.sort(key=lambda item: item.updated_at, reverse=True)
        return found[offset : offset + limit]

    def count(
        self,
        user_id: UUID,
        *,
        type: MemoryType | None = None,
        status: MemoryStatus | None = None,
        source_type: SourceType | None = None,
    ) -> int:
        found = [item for item in self.items.values() if item.user_id == user_id]
        if type is not None:
            found = [item for item in found if item.type is type]
        if status is not None:
            found = [item for item in found if item.status is status]
        if source_type is not None:
            found = [item for item in found if item.source_type is source_type]
        return len(found)

    def active_of_type(self, user_id: UUID, type: MemoryType) -> list[MemoryItem]:
        found = [
            item
            for item in self.items.values()
            if item.user_id == user_id and item.type is type and item.status is MemoryStatus.ACTIVE
        ]
        found.sort(key=lambda item: item.updated_at, reverse=True)
        return found

    def delete(self, user_id: UUID, memory_id: UUID) -> bool:
        item = self.get(user_id, memory_id)
        if item is None:
            return False
        del self.items[memory_id]
        gone = [eid for eid, row in self.episodes.items() if row.memory_id == memory_id]
        for eid in gone:
            del self.episodes[eid]
        return True

    def delete_by_scope(self, user_id: UUID, scope_key: str) -> int:
        ids = [
            item.id
            for item in self.items.values()
            if item.user_id == user_id and item.scope_key == scope_key
        ]
        for memory_id in ids:
            self.delete(user_id, memory_id)
        return len(ids)

    def delete_all(self, user_id: UUID) -> int:
        ids = [item.id for item in self.items.values() if item.user_id == user_id]
        for memory_id in ids:
            self.delete(user_id, memory_id)
        return len(ids)

    def put_episode(self, record: EpisodicRecord) -> EpisodicRecord:
        self.episodes[record.id] = record
        return record

    def get_episode_by_task(self, user_id: UUID, task_id: UUID) -> EpisodicRecord | None:
        for record in self.episodes.values():
            if record.user_id == user_id and record.task_id == task_id:
                return record
        return None

    def recent_episodes(
        self, user_id: UUID, *, intent: str | None = None, limit: int = 5
    ) -> list[EpisodicRecord]:
        found = [row for row in self.episodes.values() if row.user_id == user_id]
        if intent:
            matched = [row for row in found if row.intent == intent]
            if matched:
                found = matched
        found.sort(key=lambda row: row.started_at, reverse=True)
        return found[:limit]

    def lexical_search(self, user_id: UUID, query: str, limit: int = 20) -> list[MemoryItem]:
        tokens = [tok for tok in query.lower().split() if tok]
        scored: list[tuple[float, MemoryItem]] = []
        for item in (
            self.active_of_type(user_id, MemoryType.SEMANTIC)
            + self.active_of_type(user_id, MemoryType.PREFERENCE)
            + self.active_of_type(user_id, MemoryType.EPISODIC)
        ):
            hay = item.content.lower()
            hits = sum(1 for tok in tokens if tok in hay)
            if hits:
                scored.append((hits / max(len(tokens), 1), item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _score, item in scored[:limit]]

    def clear(self) -> None:
        self.items.clear()
        self.episodes.clear()


class PostgresMemoryStore:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    def upsert(self, item: MemoryItem) -> MemoryItem:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO memory_item (
                    id, user_id, type, subtype, content, summary, embedding, embed_model,
                    importance, confidence, source_type, source_ref, scope_key, status,
                    superseded_by, conflict_with, valid_from, valid_to, last_used_at,
                    use_count, created_at, updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (id) DO UPDATE SET
                    type = EXCLUDED.type,
                    subtype = EXCLUDED.subtype,
                    content = EXCLUDED.content,
                    summary = EXCLUDED.summary,
                    embedding = EXCLUDED.embedding,
                    embed_model = EXCLUDED.embed_model,
                    importance = EXCLUDED.importance,
                    confidence = EXCLUDED.confidence,
                    source_type = EXCLUDED.source_type,
                    source_ref = EXCLUDED.source_ref,
                    scope_key = EXCLUDED.scope_key,
                    status = EXCLUDED.status,
                    superseded_by = EXCLUDED.superseded_by,
                    conflict_with = EXCLUDED.conflict_with,
                    valid_from = EXCLUDED.valid_from,
                    valid_to = EXCLUDED.valid_to,
                    last_used_at = EXCLUDED.last_used_at,
                    use_count = EXCLUDED.use_count,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    item.id,
                    item.user_id,
                    item.type.value,
                    item.subtype,
                    item.content,
                    item.summary,
                    item.embedding,
                    item.embed_model,
                    item.importance,
                    item.confidence,
                    item.source_type.value,
                    Json(item.source_ref) if item.source_ref is not None else None,
                    item.scope_key,
                    item.status.value,
                    item.superseded_by,
                    item.conflict_with,
                    item.valid_from,
                    item.valid_to,
                    item.last_used_at,
                    item.use_count,
                    item.created_at,
                    item.updated_at,
                ),
            )
        return item

    def get(self, user_id: UUID, memory_id: UUID) -> MemoryItem | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM memory_item WHERE id = %s AND user_id = %s",
                (memory_id, user_id),
            ).fetchone()
        return _item_from_row(row) if row else None

    def list(
        self,
        user_id: UUID,
        *,
        type: MemoryType | None = None,
        status: MemoryStatus | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryItem]:
        sql = "SELECT * FROM memory_item WHERE user_id = %s"
        params: list[Any] = [user_id]
        if type is not None:
            sql += " AND type = %s"
            params.append(type.value)
        if status is not None:
            sql += " AND status = %s"
            params.append(status.value)
        if query:
            sql += " AND (content ILIKE %s OR summary ILIKE %s)"
            params.extend([f"%{query}%", f"%{query}%"])
        sql += " ORDER BY updated_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        with self._pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_item_from_row(row) for row in rows]

    def count(
        self,
        user_id: UUID,
        *,
        type: MemoryType | None = None,
        status: MemoryStatus | None = None,
        source_type: SourceType | None = None,
    ) -> int:
        sql = "SELECT count(*) AS n FROM memory_item WHERE user_id = %s"
        params: list[Any] = [user_id]
        if type is not None:
            sql += " AND type = %s"
            params.append(type.value)
        if status is not None:
            sql += " AND status = %s"
            params.append(status.value)
        if source_type is not None:
            sql += " AND source_type = %s"
            params.append(source_type.value)
        with self._pool.connection() as conn:
            row = conn.execute(sql, params).fetchone()
        return int(row["n"]) if row else 0

    def active_of_type(self, user_id: UUID, type: MemoryType) -> list[MemoryItem]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_item
                WHERE user_id = %s AND type = %s AND status = 'active'
                ORDER BY updated_at DESC
                """,
                (user_id, type.value),
            ).fetchall()
        return [_item_from_row(row) for row in rows]

    def delete(self, user_id: UUID, memory_id: UUID) -> bool:
        with self._pool.connection() as conn:
            row = conn.execute(
                "DELETE FROM memory_item WHERE id = %s AND user_id = %s RETURNING id",
                (memory_id, user_id),
            ).fetchone()
        return row is not None

    def delete_by_scope(self, user_id: UUID, scope_key: str) -> int:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                WITH gone AS (
                    DELETE FROM memory_item
                    WHERE user_id = %s AND scope_key = %s
                    RETURNING id
                )
                SELECT count(*) AS n FROM gone
                """,
                (user_id, scope_key),
            ).fetchone()
        return int(row["n"]) if row else 0

    def delete_all(self, user_id: UUID) -> int:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                WITH gone AS (
                    DELETE FROM memory_item WHERE user_id = %s RETURNING id
                )
                SELECT count(*) AS n FROM gone
                """,
                (user_id,),
            ).fetchone()
        return int(row["n"]) if row else 0

    def put_episode(self, record: EpisodicRecord) -> EpisodicRecord:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO episodic_record (
                    id, memory_id, user_id, task_id, title, intent, tools_used,
                    skill_id, outcome, decisions, user_edits, duration_ms,
                    started_at, ended_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    record.id,
                    record.memory_id,
                    record.user_id,
                    record.task_id,
                    record.title,
                    record.intent,
                    record.tools_used,
                    record.skill_id,
                    record.outcome.value,
                    Json(record.decisions),
                    Json(record.user_edits),
                    record.duration_ms,
                    record.started_at,
                    record.ended_at,
                ),
            )
        return record

    def get_episode_by_task(self, user_id: UUID, task_id: UUID) -> EpisodicRecord | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM episodic_record
                WHERE user_id = %s AND task_id = %s
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (user_id, task_id),
            ).fetchone()
        return _episode_from_row(row) if row else None

    def recent_episodes(
        self, user_id: UUID, *, intent: str | None = None, limit: int = 5
    ) -> list[EpisodicRecord]:
        sql = "SELECT * FROM episodic_record WHERE user_id = %s"
        params: list[Any] = [user_id]
        if intent:
            sql += " AND intent = %s"
            params.append(intent)
        sql += " ORDER BY started_at DESC LIMIT %s"
        params.append(limit)
        with self._pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        records = [_episode_from_row(row) for row in rows]
        if intent and not records:
            return self.recent_episodes(user_id, intent=None, limit=limit)
        return records

    def lexical_search(self, user_id: UUID, query: str, limit: int = 20) -> list[MemoryItem]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT *, ts_rank(tsv, plainto_tsquery('simple', %s)) AS rank
                FROM memory_item
                WHERE user_id = %s AND status = 'active'
                  AND tsv @@ plainto_tsquery('simple', %s)
                ORDER BY rank DESC
                LIMIT %s
                """,
                (query, user_id, query, limit),
            ).fetchall()
        return [_item_from_row(row) for row in rows]

    def clear(self) -> None:
        with self._pool.connection() as conn:
            conn.execute("TRUNCATE memory_item CASCADE")
            conn.execute("TRUNCATE episodic_record")
