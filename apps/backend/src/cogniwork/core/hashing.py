"""不可逆哈希。

审计与授权记录只记「做了什么」，不记「内容是什么」（硬约束 8）。
IP 进 consent_record 之前必须先哈希；pepper 来自配置，避免彩虹表。
"""

from __future__ import annotations

import hashlib
from uuid import UUID


def hash_ip(ip: str, pepper: str) -> str:
    return hashlib.sha256(f"{pepper}:{ip}".encode()).hexdigest()


def anonymize_user_id(user_id: str, pepper: str) -> UUID:
    """账号删除后 consent_record.user_id 的去标识替换（B1）。

    不可逆：没有 pepper 就还原不了原 user_id。列类型仍是 uuid，
    所以把哈希截成 16 字节。这不是业务主键，不必是 UUIDv7。
    """
    digest = hashlib.sha256(f"{pepper}:account:{user_id}".encode()).digest()
    return UUID(bytes=digest[:16])
