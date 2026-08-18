"""账号存储。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg import Error as PsycopgError
from psycopg.errors import UniqueViolation

from cogniwork.core.clock import now
from cogniwork.core.errors import Conflict
from cogniwork.core.ids import new_id

from .models import Account


def _normalize_email(email: str) -> str:
    return email.strip().lower()


class InMemoryAccountStore:
    def __init__(self) -> None:
        self._by_id: dict[UUID, Account] = {}
        self._by_email: dict[str, UUID] = {}

    def create(self, email: str, password_hash: str) -> Account:
        normalized = _normalize_email(email)
        if normalized in self._by_email:
            raise Conflict("An account with this email already exists.")
        created = now()
        account = Account(
            id=new_id(),
            email=normalized,
            password_hash=password_hash,
            created_at=created,
            updated_at=created,
        )
        self._by_id[account.id] = account
        self._by_email[normalized] = account.id
        return account

    def get_by_id(self, account_id: UUID) -> Account | None:
        return self._by_id.get(account_id)

    def get_by_email(self, email: str) -> Account | None:
        account_id = self._by_email.get(_normalize_email(email))
        if account_id is None:
            return None
        return self._by_id.get(account_id)

    def clear(self) -> None:
        self._by_id.clear()
        self._by_email.clear()


class PostgresAccountStore:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    def create(self, email: str, password_hash: str) -> Account:
        normalized = _normalize_email(email)
        created = now()
        account_id = new_id()
        try:
            with self._pool.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO account (id, email, password_hash, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (account_id, normalized, password_hash, created, created),
                )
        except UniqueViolation:
            raise Conflict("An account with this email already exists.") from None
        except PsycopgError as exc:
            if getattr(exc, "sqlstate", None) == "23505":
                raise Conflict("An account with this email already exists.") from None
            raise
        return Account(
            id=account_id,
            email=normalized,
            password_hash=password_hash,
            created_at=created,
            updated_at=created,
        )

    def get_by_id(self, account_id: UUID) -> Account | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT id, email, password_hash, created_at, updated_at
                FROM account WHERE id = %s
                """,
                (account_id,),
            ).fetchone()
        return _row_to_account(row)

    def get_by_email(self, email: str) -> Account | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT id, email, password_hash, created_at, updated_at
                FROM account WHERE lower(email) = %s
                """,
                (_normalize_email(email),),
            ).fetchone()
        return _row_to_account(row)

    def clear(self) -> None:
        with self._pool.connection() as conn:
            conn.execute("TRUNCATE account CASCADE")


def _row_to_account(row: dict[str, Any] | None) -> Account | None:
    if row is None:
        return None
    return Account(
        id=row["id"],
        email=row["email"],
        password_hash=row["password_hash"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
