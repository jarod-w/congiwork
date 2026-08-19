"""Personal Profile domain model (P0-01 §4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class FieldSource(StrEnum):
    INTERVIEW = "interview"
    MANUAL = "manual"
    EXTRACTED = "extracted"


class FieldStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    REJECTED = "rejected"
    STALE = "stale"


class InterviewStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    AWAITING_SUMMARY = "awaiting_summary"
    SKIPPED = "skipped"
    COMPLETED = "completed"


# Controlled vocabulary (P0-01 §4.1). Unknown keys fall into custom.*.
CONTROLLED_KEYS = (
    "role",
    "industry",
    "company_context",
    "business_goals",
    "tools",
    "recurring_deliverables",
    "preferences.writing_tone",
    "preferences.output_format",
    "preferences.language",
    "working_hours",
)

ARRAY_KEYS = {
    "company_context",
    "business_goals",
    "tools",
    "recurring_deliverables",
    "custom.report_outline",
}

INJECT_WEIGHT = {
    "role": 3,
    "industry": 3,
    "company_context": 3,
    "business_goals": 3,
    "preferences.writing_tone": 3,
    "preferences.output_format": 3,
    "preferences.language": 3,
    "tools": 2,
    "recurring_deliverables": 2,
    "working_hours": 1,
}

VALUE_CHAR_LIMIT = 200
CARD_TOKEN_BUDGET = 600


def normalize_key(key: str) -> str:
    text = key.strip()
    if not text:
        raise ValueError("empty key")
    if text in CONTROLLED_KEYS or text.startswith("custom."):
        return text
    return f"custom.{text}"


def clamp_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()[:VALUE_CHAR_LIMIT]
    if isinstance(value, list):
        return [clamp_value(item) for item in value if str(item).strip()][:20]
    if isinstance(value, dict):
        return {str(k)[:80]: clamp_value(v) for k, v in list(value.items())[:20]}
    return value


@dataclass(slots=True)
class Profile:
    id: UUID
    user_id: UUID
    version: int
    completed: bool
    created_at: datetime
    updated_at: datetime
    org_id: UUID | None = None
    archived_at: datetime | None = None
    archive_reason: str | None = None


@dataclass(slots=True)
class ProfileField:
    id: UUID
    profile_id: UUID
    user_id: UUID
    key: str
    value: Any
    source: FieldSource
    status: FieldStatus
    created_at: datetime
    updated_at: datetime
    confidence: float = 1.0
    evidence: dict[str, Any] | None = None


@dataclass(slots=True)
class InterviewSession:
    id: UUID
    user_id: UUID
    profile_id: UUID
    status: InterviewStatus
    round: int
    created_at: datetime
    updated_at: datetime
    question_key: str | None = None
    answers: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProfileDraft:
    key: str
    value: Any
    evidence: dict[str, Any] | None = None
    confidence: float = 0.7
