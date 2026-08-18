"""注册与登录。"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from cogniwork.core.errors import Unauthorized

from .models import Account
from .passwords import hash_password, verify_password, verify_unknown_user


class AccountStore(Protocol):
    def create(self, email: str, password_hash: str) -> Account: ...
    def get_by_id(self, account_id: UUID) -> Account | None: ...
    def get_by_email(self, email: str) -> Account | None: ...


class AuthService:
    def __init__(self, store: AccountStore) -> None:
        self._store = store

    def register(self, email: str, password: str) -> Account:
        return self._store.create(email, hash_password(password))

    def login(self, email: str, password: str) -> Account:
        account = self._store.get_by_email(email)
        if account is None:
            verify_unknown_user(password)
            raise Unauthorized("Invalid email or password.")
        if not verify_password(password, account.password_hash):
            raise Unauthorized("Invalid email or password.")
        return account

    def get(self, account_id: UUID) -> Account | None:
        return self._store.get_by_id(account_id)
