"""Memory OS 领域模型（P0-02 §4）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class MemoryType(StrEnum):
    SEMANTIC = "semantic"
    EPISODIC = "episodic"
    PREFERENCE = "preference"


class MemoryStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class SourceType(StrEnum):
    USER_EXPLICIT = "user_explicit"
    TASK_EXTRACTED = "task_extracted"
    FILE_INGEST = "file_ingest"
    APPROVAL_EDIT = "approval_edit"
    # 任务历史是系统事实，不是「关于用户的抽取」（P0-02 §2）。
    SYSTEM = "system"


class EpisodeOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"


@dataclass(slots=True)
class MemoryItem:
    id: UUID
    user_id: UUID
    type: MemoryType
    content: str
    source_type: SourceType
    status: MemoryStatus
    created_at: datetime
    updated_at: datetime
    valid_from: datetime
    subtype: str | None = None
    summary: str | None = None
    embedding: list[float] | None = None
    embed_model: str | None = None
    importance: int = 3
    confidence: float = 1.0
    source_ref: dict[str, Any] | None = None
    scope_key: str | None = None
    superseded_by: UUID | None = None
    conflict_with: UUID | None = None
    valid_to: datetime | None = None
    last_used_at: datetime | None = None
    use_count: int = 0


@dataclass(slots=True)
class EpisodicRecord:
    id: UUID
    memory_id: UUID
    user_id: UUID
    task_id: UUID
    title: str
    outcome: EpisodeOutcome
    started_at: datetime
    intent: str | None = None
    tools_used: list[str] = field(default_factory=list)
    skill_id: UUID | None = None
    decisions: list[dict[str, Any]] = field(default_factory=list)
    user_edits: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: int | None = None
    ended_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MemoryDraft:
    type: MemoryType
    content: str
    summary: str | None = None
    subtype: str | None = None
    importance: int = 3
    evidence_quote: str | None = None
    source_type: SourceType = SourceType.TASK_EXTRACTED
    scope_key: str | None = None


@dataclass(frozen=True, slots=True)
class ScoredMemory:
    item: MemoryItem
    score: float
    cosine: float
    lexical: float
    recency: float
    importance: float


@dataclass(frozen=True, slots=True)
class MemoryBundle:
    preferences: list[ScoredMemory]
    facts: list[ScoredMemory]
    past: list[ScoredMemory]
    xml: str
    used_tokens: int
