"""不可逆哈希。

审计与授权记录只记「做了什么」，不记「内容是什么」（硬约束 8）。
IP 进 consent_record 之前必须先哈希；pepper 来自配置，避免彩虹表。
"""

from __future__ import annotations

import hashlib


def hash_ip(ip: str, pepper: str) -> str:
    return hashlib.sha256(f"{pepper}:{ip}".encode()).hexdigest()
