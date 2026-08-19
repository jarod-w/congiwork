"""Tool connection + credential persistence (P0-05 §5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.types.json import Json

from cogniwork.core.clock import now
from cogniwork.core.ids import new_id


@dataclass(slots=True)
class ToolConnection:
    id: UUID
    user_id: UUID
    provider: str
    granted_scopes: list[str]
    oauth_scopes: list[str]
    status: str
    created_at: datetime
    updated_at: datetime
    account_label: str | None = None
    last_used_at: datetime | None = None
    last_error: dict[str, Any] | None = None


@dataclass(slots=True)
class ToolCredential:
    connection_id: UUID
    ciphertext: bytes
    dek_wrapped: bytes
    key_version: int
    updated_at: datetime
    expires_at: datetime | None = None


@dataclass(slots=True)
class OAuthState:
    state: str
    user_id: UUID
    provider: str
    granted_scopes: list[str]
    created_at: datetime


def _conn_from_row(row: dict[str, Any]) -> ToolConnection:
    return ToolConnection(
        id=row["id"],
        user_id=row["user_id"],
        provider=row["provider"],
        account_label=row.get("account_label"),
        granted_scopes=list(row.get("granted_scopes") or []),
        oauth_scopes=list(row.get("oauth_scopes") or []),
        status=row["status"],
        last_used_at=row.get("last_used_at"),
        last_error=row.get("last_error"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class InMemoryToolStore:
    def __init__(self) -> None:
        self.connections: dict[UUID, ToolConnection] = {}
        self.credentials: dict[UUID, ToolCredential] = {}
        self.states: dict[str, OAuthState] = {}

    def upsert_connection(self, item: ToolConnection) -> ToolConnection:
        self.connections[item.id] = item
        return item

    def get_connection(self, user_id: UUID, connection_id: UUID) -> ToolConnection | None:
        item = self.connections.get(connection_id)
        if item is None or item.user_id != user_id:
            return None
        return item

    def list_connections(self, user_id: UUID) -> list[ToolConnection]:
        found = [item for item in self.connections.values() if item.user_id == user_id]
        found.sort(key=lambda item: item.updated_at, reverse=True)
        return found

    def active_for_provider(self, user_id: UUID, provider: str) -> ToolConnection | None:
        found = [
            item
            for item in self.connections.values()
            if item.user_id == user_id and item.provider == provider and item.status == "active"
        ]
        found.sort(key=lambda item: item.updated_at, reverse=True)
        return found[0] if found else None

    def put_credential(self, item: ToolCredential) -> ToolCredential:
        self.credentials[item.connection_id] = item
        return item

    def get_credential(self, connection_id: UUID) -> ToolCredential | None:
        return self.credentials.get(connection_id)

    def delete_credential(self, connection_id: UUID) -> bool:
        return self.credentials.pop(connection_id, None) is not None

    def put_state(self, item: OAuthState) -> OAuthState:
        self.states[item.state] = item
        return item

    def pop_state(self, state: str) -> OAuthState | None:
        return self.states.pop(state, None)

    def delete_for_user(self, user_id: UUID) -> int:
        ids = [item.id for item in self.connections.values() if item.user_id == user_id]
        for cid in ids:
            self.credentials.pop(cid, None)
            del self.connections[cid]
        gone = [key for key, row in self.states.items() if row.user_id == user_id]
        for key in gone:
            del self.states[key]
        return len(ids)

    def clear(self) -> None:
        self.connections.clear()
        self.credentials.clear()
        self.states.clear()


class PostgresToolStore:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    def upsert_connection(self, item: ToolConnection) -> ToolConnection:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO tool_connection (
                    id, user_id, provider, account_label, granted_scopes, oauth_scopes,
                    status, last_used_at, last_error, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    account_label = EXCLUDED.account_label,
                    granted_scopes = EXCLUDED.granted_scopes,
                    oauth_scopes = EXCLUDED.oauth_scopes,
                    status = EXCLUDED.status,
                    last_used_at = EXCLUDED.last_used_at,
                    last_error = EXCLUDED.last_error,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    item.id,
                    item.user_id,
                    item.provider,
                    item.account_label,
                    item.granted_scopes,
                    item.oauth_scopes,
                    item.status,
                    item.last_used_at,
                    Json(item.last_error) if item.last_error is not None else None,
                    item.created_at,
                    item.updated_at,
                ),
            )
        return item

    def get_connection(self, user_id: UUID, connection_id: UUID) -> ToolConnection | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM tool_connection WHERE id = %s AND user_id = %s",
                (connection_id, user_id),
            ).fetchone()
        return _conn_from_row(row) if row else None

    def list_connections(self, user_id: UUID) -> list[ToolConnection]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tool_connection
                WHERE user_id = %s
                ORDER BY updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [_conn_from_row(row) for row in rows]

    def active_for_provider(self, user_id: UUID, provider: str) -> ToolConnection | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM tool_connection
                WHERE user_id = %s AND provider = %s AND status = 'active'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (user_id, provider),
            ).fetchone()
        return _conn_from_row(row) if row else None

    def put_credential(self, item: ToolCredential) -> ToolCredential:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO tool_credential (
                    connection_id, ciphertext, dek_wrapped, key_version, expires_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (connection_id) DO UPDATE SET
                    ciphertext = EXCLUDED.ciphertext,
                    dek_wrapped = EXCLUDED.dek_wrapped,
                    key_version = EXCLUDED.key_version,
                    expires_at = EXCLUDED.expires_at,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    item.connection_id,
                    item.ciphertext,
                    item.dek_wrapped,
                    item.key_version,
                    item.expires_at,
                    item.updated_at,
                ),
            )
        return item

    def get_credential(self, connection_id: UUID) -> ToolCredential | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM tool_credential WHERE connection_id = %s",
                (connection_id,),
            ).fetchone()
        if row is None:
            return None
        return ToolCredential(
            connection_id=row["connection_id"],
            ciphertext=bytes(row["ciphertext"]),
            dek_wrapped=bytes(row["dek_wrapped"]),
            key_version=int(row["key_version"]),
            expires_at=row.get("expires_at"),
            updated_at=row["updated_at"],
        )

    def delete_credential(self, connection_id: UUID) -> bool:
        with self._pool.connection() as conn:
            row = conn.execute(
                "DELETE FROM tool_credential WHERE connection_id = %s RETURNING connection_id",
                (connection_id,),
            ).fetchone()
        return row is not None

    def put_state(self, item: OAuthState) -> OAuthState:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO oauth_state (state, user_id, provider, granted_scopes, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (state) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    provider = EXCLUDED.provider,
                    granted_scopes = EXCLUDED.granted_scopes
                """,
                (item.state, item.user_id, item.provider, item.granted_scopes, item.created_at),
            )
        return item

    def pop_state(self, state: str) -> OAuthState | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "DELETE FROM oauth_state WHERE state = %s RETURNING *",
                (state,),
            ).fetchone()
        if row is None:
            return None
        return OAuthState(
            state=row["state"],
            user_id=row["user_id"],
            provider=row["provider"],
            granted_scopes=list(row.get("granted_scopes") or []),
            created_at=row["created_at"],
        )

    def delete_for_user(self, user_id: UUID) -> int:
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM oauth_state WHERE user_id = %s", (user_id,))
            row = conn.execute(
                """
                WITH gone AS (
                    DELETE FROM tool_connection WHERE user_id = %s RETURNING id
                )
                SELECT count(*) AS n FROM gone
                """,
                (user_id,),
            ).fetchone()
        return int(row["n"]) if row else 0

    def clear(self) -> None:
        with self._pool.connection() as conn:
            conn.execute("TRUNCATE tool_connection CASCADE")
            conn.execute("TRUNCATE oauth_state")


def new_connection(
    user_id: UUID,
    provider: str,
    granted_scopes: list[str],
    oauth_scopes: list[str],
    account_label: str | None,
) -> ToolConnection:
    created = now()
    return ToolConnection(
        id=new_id(),
        user_id=user_id,
        provider=provider,
        account_label=account_label,
        granted_scopes=granted_scopes,
        oauth_scopes=oauth_scopes,
        status="active",
        created_at=created,
        updated_at=created,
    )
