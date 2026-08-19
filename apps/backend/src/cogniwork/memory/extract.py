"""任务终态抽取候选。不阻塞用户拿结果（P0-02 §5.1）。"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from .models import MemoryDraft, MemoryType, SourceType
from .service import MemoryService

_REMEMBER = re.compile(
    r"^\s*(?:remember(?:\s+that)?|记住)[：:]?\s+(.+)$",
    re.IGNORECASE,
)
_PREFER = re.compile(
    r"\b(prefer|always|never|don't use|do not use|不用|偏好|请用)\b",
    re.IGNORECASE,
)


def extract_from_task(service: MemoryService, task: Any) -> list:
    message = str((task.input or {}).get("message") or "")
    drafts = drafts_from_text(message)
    if not drafts:
        return []
    source = {"task_id": str(task.id), "message_id": None}
    return service.propose(task.user_id, drafts, source)


def drafts_from_text(message: str) -> list[MemoryDraft]:
    drafts: list[MemoryDraft] = []
    for line in message.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        remembered = _REMEMBER.match(stripped)
        if remembered:
            content = remembered.group(1).strip().rstrip(".")
            if content:
                drafts.append(
                    MemoryDraft(
                        type=MemoryType.SEMANTIC,
                        content=content,
                        summary=content[:120],
                        importance=4,
                        evidence_quote=stripped,
                        source_type=SourceType.TASK_EXTRACTED,
                    )
                )
                continue
        if _PREFER.search(stripped) and len(stripped) < 240:
            drafts.append(
                MemoryDraft(
                    type=MemoryType.PREFERENCE,
                    content=stripped.rstrip("."),
                    summary=stripped[:120],
                    importance=3,
                    evidence_quote=stripped,
                    source_type=SourceType.TASK_EXTRACTED,
                    scope_key="memory:preference:auto_write",
                )
            )
    return drafts[:5]


def propose_from_edits(
    service: MemoryService, user_id: UUID, edits: list[dict[str, Any]], task_id: UUID
) -> list:
    if not edits:
        return []
    drafts = []
    for edit in edits[:5]:
        field = str(edit.get("field") or "text")
        before = str(edit.get("before") or "")
        after = str(edit.get("after") or "")
        if not after or after == before:
            continue
        drafts.append(
            MemoryDraft(
                type=MemoryType.PREFERENCE,
                content=f"When editing {field}, you changed it to: {after[:200]}",
                summary=f"Prefers «{after[:80]}» for {field}",
                importance=4,
                evidence_quote=after[:180],
                source_type=SourceType.APPROVAL_EDIT,
                scope_key="memory:preference:auto_write",
            )
        )
    return service.propose(user_id, drafts, {"task_id": str(task_id)})
