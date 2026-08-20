"""Create a Skill draft from a finished task (P0-06 §5.2).

Phase 1 hands parameterization to the user: we propose candidates, they pick.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from cogniwork.core.errors import InvalidRequest
from cogniwork.skill.draft import _finalize_draft, connected_tool_names
from cogniwork.skill.workflow import normalize_workflow


def draft_from_task(task: Any, *, connected_tools: list[str] | None = None) -> dict[str, Any]:
    steps = list(getattr(task, "steps", None) or [])
    if not steps:
        raise InvalidRequest("This task has no steps to save as a skill.")
    normalized = _normalize_steps(steps)
    candidates = _parameter_candidates(task, normalized)
    workflow_raw = []
    fields = [c["key"] for c in candidates]
    if fields:
        workflow_raw.append(
            {
                "id": "s1",
                "type": "collect_input",
                "title": "Confirm the values that may change next time",
                "fields": fields,
            }
        )
    for index, item in enumerate(normalized, start=len(workflow_raw) + 1):
        workflow_raw.append({**item, "id": item.get("id") or f"s{index}"})
    parsed = {
        "name": (task.title or "Saved from a task")[:80],
        "description": str((task.input or {}).get("message") or task.title or "")[:1000],
        "parameters": candidates,
        "steps": workflow_raw,
        "source_ref": {"task_id": str(task.id)},
    }
    draft = _finalize_draft(parsed, set(connected_tools or []), source="from_task")
    draft["parameter_candidates"] = candidates
    draft["source_ref"] = {"task_id": str(task.id)}
    return draft


def _normalize_steps(steps: list[Any]) -> list[dict[str, Any]]:
    """Merge consecutive llm steps, drop failed retries, drop clarify round-trips."""
    kept: list[dict[str, Any]] = []
    for step in steps:
        status = getattr(step.status, "value", step.status)
        title = str(step.title or "")
        if status == "failed":
            continue
        if _is_clarify(title):
            continue
        kind = getattr(step.type, "value", step.type)
        mapped = _map_type(str(kind), title, step)
        if kept and kept[-1]["type"] == "llm" and mapped["type"] == "llm" and status == "succeeded":
            kept[-1]["instruction"] = (
                (kept[-1].get("instruction") or kept[-1]["title"])
                + " "
                + mapped.get("instruction", mapped["title"])
            )
            continue
        kept.append(mapped)
    if not kept:
        kept.append(
            {
                "type": "llm",
                "title": "Repeat the work from this task",
                "instruction": "Repeat the successful work from the source task.",
            }
        )
    return normalize_workflow(kept)


def _map_type(kind: str, title: str, step: Any) -> dict[str, Any]:
    if kind == "tool":
        return {
            "type": "tool",
            "title": title or "Use a tool",
            "tool": _tool_from_digest(step),
            "on_error": "ask_user",
        }
    if kind == "approval":
        return {"type": "approval", "title": title or "Confirm before continuing"}
    if kind == "skill":
        return {"type": "llm", "title": title or "Continue the nested work", "instruction": title}
    return {
        "type": "llm",
        "title": title or "Think through the next step",
        "instruction": title,
    }


def _tool_from_digest(step: Any) -> str | None:
    digest = getattr(step, "input_digest", None) or {}
    if isinstance(digest, dict):
        for key in ("tool", "name"):
            if digest.get(key):
                return str(digest[key])
    return None


def _is_clarify(title: str) -> bool:
    lowered = title.lower()
    return "clarif" in lowered or "ask the user" in lowered or "ask_user" in lowered


def _parameter_candidates(task: Any, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    message = str((task.input or {}).get("message") or "")
    found: list[dict[str, Any]] = []
    for match in re.finditer(
        r"\b(Q[1-4]\s?\d{2,4}|20\d{2}-\d{2}-\d{2}|\d+\s?(days|weeks|months))\b",
        message,
        re.I,
    ):
        found.append(
            {
                "key": _slug(match.group(0)),
                "example": match.group(0),
                "ask": "Might this value change the next time you run it?",
            }
        )
    if "channel" in message.lower() and all(item["key"] != "channels" for item in found):
        found.append(
            {
                "key": "channels",
                "example": "all",
                "ask": "Might this value change the next time you run it?",
            }
        )
    return found[:8]


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return (slug or "value")[:32]


def connected_names_for(user_id: UUID, tools: Any) -> list[str]:
    return connected_tool_names(tools, user_id)
