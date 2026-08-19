"""Turn a finished task into Profile candidates when the fact looks stable.

extracted drafts always go pending (PF-4). Heuristic on purpose: a wrong
guess that the user confirms is cheaper than an LLM that writes silently.
"""

from __future__ import annotations

import re
from typing import Any

from .models import CONTROLLED_KEYS, ProfileDraft

_ROLE = re.compile(
    r"\b(?:i am|i'm|as a|my role is)\s+(.{3,80})",
    re.IGNORECASE,
)
_TOOLS = re.compile(
    r"\b(?:we use|i use|using)\s+(notion|gmail|excel|sheets|hubspot|slack|github)\b",
    re.IGNORECASE,
)
_GOAL = re.compile(
    r"\b(?:goal|target|this quarter|q[1-4])\b.{0,80}",
    re.IGNORECASE,
)


def drafts_from_task(task: Any) -> list[ProfileDraft]:
    message = str((task.input or {}).get("message") or "")
    drafts: list[ProfileDraft] = []
    evidence = {"task_id": str(task.id), "quote": message[:180]}
    role = _ROLE.search(message)
    if role:
        drafts.append(ProfileDraft(key="role", value=role.group(1).strip(" .,"), evidence=evidence))
    tools = [m.group(1) for m in _TOOLS.finditer(message)]
    if tools:
        drafts.append(ProfileDraft(key="tools", value=tools, evidence=evidence))
    goal = _GOAL.search(message)
    if goal and len(goal.group(0)) < 180:
        drafts.append(
            ProfileDraft(key="business_goals", value=[goal.group(0).strip()], evidence=evidence)
        )
    return [d for d in drafts if d.key in CONTROLLED_KEYS][:3]
