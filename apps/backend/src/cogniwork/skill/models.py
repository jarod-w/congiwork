"""Skill domain model (P0-06 §4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

STEP_TYPES = ("collect_input", "llm", "tool", "approval", "skill")
ON_ERROR = ("stop", "ask_user", "skip", "retry")
SOURCES = ("manual", "from_task", "semi_auto", "preset_copy")
STATUSES = ("draft", "active", "archived")
TRIGGER_TYPES = ("manual", "keyword")
CHANGED_BY = ("user", "system")


class SkillSource(StrEnum):
    MANUAL = "manual"
    FROM_TASK = "from_task"
    SEMI_AUTO = "semi_auto"
    PRESET_COPY = "preset_copy"


class SkillStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


@dataclass(slots=True)
class Skill:
    id: UUID
    user_id: UUID
    name: str
    description: str
    trigger: dict[str, Any]
    input_schema: dict[str, Any]
    workflow: list[dict[str, Any]]
    tools: list[str]
    required_scopes: list[str]
    source: SkillSource
    version: int
    status: SkillStatus
    created_at: datetime
    updated_at: datetime
    source_ref: dict[str, Any] | None = None
    run_count: int = 0
    success_count: int = 0
    last_run_at: datetime | None = None

    @property
    def success_rate(self) -> float | None:
        if self.run_count <= 0:
            return None
        return self.success_count / self.run_count


@dataclass(slots=True)
class SkillVersion:
    skill_id: UUID
    version: int
    snapshot: dict[str, Any]
    changed_by: str
    created_at: datetime
    change_note: str | None = None


@dataclass(slots=True)
class CustomLlmProvider:
    id: UUID
    user_id: UUID
    name: str
    base_url: str
    model: str
    ciphertext: bytes
    dek_wrapped: bytes
    key_version: int
    capabilities: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime
    unit_cost_usd: float | None = None
    last_probed_at: datetime | None = None


@dataclass(slots=True)
class ProductEvent:
    id: UUID
    user_id: UUID
    name: str
    payload: dict[str, Any]
    created_at: datetime
    extra: dict[str, Any] = field(default_factory=dict)
