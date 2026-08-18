"""密码哈希。

凭据不落明文（硬约束 9）：这里只产生/校验 argon2 哈希，调用方不得把
password 或 password_hash 写进日志、trace、错误详情。
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()
# 未知邮箱也走一次 verify，避免「邮箱不存在」比「密码错误」更快。
_DUMMY_HASH = _hasher.hash("not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def verify_unknown_user(password: str) -> None:
    verify_password(password, _DUMMY_HASH)
