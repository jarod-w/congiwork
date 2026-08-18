"""Task / Conversation / Step 领域模型（P0-03 §3）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class TaskStatus(StrEnum):
    CREATED = "created"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


TERMINAL_STATUSES = frozenset(
    {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.TIMED_OUT,
    }
)


class StepType(StrEnum):
    LLM = "llm"
    TOOL = "tool"
    APPROVAL = "approval"
    SKILL = "skill"
    SUBTASK = "subtask"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class Surface(StrEnum):
    WEB = "web"
    DESKTOP = "desktop"
    BROWSER_EXT = "browser_ext"
    API = "api"


# P0-03 §3 状态机。非法迁移在 TaskEngine 里拒绝，而不是靠调用方自觉。
ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset({TaskStatus.PLANNING, TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.PLANNING: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.FAILED}),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.TIMED_OUT,
            TaskStatus.CANCELLED,
            TaskStatus.PLANNING,
        }
    ),
    TaskStatus.WAITING_APPROVAL: frozenset(
        {TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.TIMED_OUT}
    ),
    TaskStatus.SUCCEEDED: frozenset(),
    TaskStatus.FAILED: frozenset({TaskStatus.RUNNING}),  # resume
    TaskStatus.CANCELLED: frozenset(),
    TaskStatus.TIMED_OUT: frozenset({TaskStatus.RUNNING}),
}


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


@dataclass(slots=True)
class Conversation:
    id: UUID
    user_id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class TaskStep:
    id: UUID
    task_id: UUID
    seq: int
    type: StepType
    title: str
    status: StepStatus
    scope_key: str | None
    input_digest: dict[str, Any] | None
    output_digest: dict[str, Any] | None
    error: dict[str, Any] | None
    duration_ms: int | None
    created_at: datetime


@dataclass(slots=True)
class Task:
    id: UUID
    user_id: UUID
    conversation_id: UUID
    title: str | None
    intent: str | None
    status: TaskStatus
    surface: Surface
    skill_id: UUID | None
    input: dict[str, Any]
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    thread_id: str
    cost_usd: float
    token_in: int
    token_out: int
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime
    steps: list[TaskStep] = field(default_factory=list)


@dataclass(slots=True)
class UploadedFile:
    id: UUID
    user_id: UUID
    filename: str
    content_type: str
    size_bytes: int
    persist: bool
    content: bytes
    created_at: datetime


@dataclass(slots=True)
class Artifact:
    id: UUID
    user_id: UUID
    task_id: UUID
    filename: str
    content_type: str
    size_bytes: int
    content: bytes
    created_at: datetime
