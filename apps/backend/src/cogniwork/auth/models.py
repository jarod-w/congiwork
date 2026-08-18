"""账号领域模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Account:
    id: UUID
    email: str
    password_hash: str
    created_at: datetime
    updated_at: datetime
