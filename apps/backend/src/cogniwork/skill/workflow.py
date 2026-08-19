"""Workflow validation and derived fields (P0-06 §4.2 / §9).

required_scopes is computed from the tools actually named in the workflow.
Users cannot type it in. A tool step with no tool is allowed — the editor
must be able to save that state (P0-06 §6).
"""

from __future__ import annotations

from typing import Any

from cogniwork.consent.models import Risk
from cogniwork.core.errors import InvalidRequest
from cogniwork.skill.models import ON_ERROR, STEP_TYPES, TRIGGER_TYPES
from cogniwork.tools.catalog import load_catalog

MAX_STEPS = 20
MAX_NESTING = 1


def normalize_trigger(raw: Any) -> dict[str, Any]:
    data = dict(raw or {"type": "manual"})
    kind = str(data.get("type") or "manual")
    if kind not in TRIGGER_TYPES:
        raise InvalidRequest("Unknown trigger type.", details={"type": kind})
    if kind == "keyword":
        patterns = [str(p).strip() for p in (data.get("patterns") or []) if str(p).strip()]
        return {"type": "keyword", "patterns": patterns[:20]}
    return {"type": "manual"}


def normalize_input_schema(raw: Any) -> dict[str, Any]:
    schema = dict(raw or {"type": "object", "properties": {}})
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    if schema["type"] != "object":
        raise InvalidRequest("input_schema must be a JSON object schema.")
    return schema


def normalize_workflow(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise InvalidRequest("A skill needs at least one step.")
    if len(raw) > MAX_STEPS:
        raise InvalidRequest(f"A skill can have at most {MAX_STEPS} steps.")
    seen: set[str] = set()
    steps: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise InvalidRequest("Each workflow step must be an object.")
        step = _normalize_step(item, index)
        if step["id"] in seen:
            raise InvalidRequest("Duplicate step id.", details={"id": step["id"]})
        seen.add(step["id"])
        steps.append(step)
    return steps


def _normalize_step(item: dict[str, Any], index: int) -> dict[str, Any]:
    step_type = str(item.get("type") or "")
    if step_type not in STEP_TYPES:
        raise InvalidRequest("Unknown step type.", details={"type": step_type})
    title = str(item.get("title") or "").strip()
    if not title:
        raise InvalidRequest("Every step needs a title in the user's language.")
    step_id = str(item.get("id") or f"s{index}")
    step: dict[str, Any] = {
        "id": step_id,
        "type": step_type,
        "title": title[:200],
    }
    if item.get("needs_clarification"):
        step["needs_clarification"] = True
    if step_type == "collect_input":
        fields = [str(f).strip() for f in (item.get("fields") or []) if str(f).strip()]
        step["fields"] = fields
    elif step_type == "llm":
        step["instruction"] = str(item.get("instruction") or title)[:4000]
        step["uses_memory"] = bool(item.get("uses_memory"))
    elif step_type == "tool":
        tool = item.get("tool")
        step["tool"] = str(tool).strip() if tool else None
        step["args_hint"] = dict(item.get("args_hint") or {})
        on_error = str(item.get("on_error") or "ask_user")
        if on_error not in ON_ERROR:
            raise InvalidRequest("Unknown on_error.", details={"on_error": on_error})
        if _tool_is_irreversible(step["tool"]) and on_error == "retry":
            # irreversible must not auto-retry (P0-05 §6).
            raise InvalidRequest(
                "This step cannot retry automatically — it cannot be undone.",
                details={"tool": step["tool"]},
            )
        step["on_error"] = on_error
    elif step_type == "approval":
        step["preview_from"] = str(item.get("preview_from") or "") or None
    elif step_type == "skill":
        nested = str(item.get("skill_id") or item.get("skill") or "").strip()
        if not nested:
            raise InvalidRequest("A nested skill step needs skill_id.")
        step["skill_id"] = nested
    return step


def _tool_is_irreversible(name: str | None) -> bool:
    if not name:
        return False
    found = load_catalog().tool(name)
    return found is not None and found.risk is Risk.IRREVERSIBLE


def derive_tools_and_scopes(workflow: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    catalog = load_catalog()
    tools: list[str] = []
    scopes: list[str] = []
    for step in workflow:
        if step.get("type") != "tool":
            continue
        name = step.get("tool")
        if not name:
            continue
        if name not in tools:
            tools.append(name)
        found = catalog.tool(name)
        if found is None:
            # Unrecognised names stay as needs_clarification rather than
            # inventing a Scope. Callers mark the step when drafting.
            continue
        if found.scope_key and found.scope_key not in scopes:
            scopes.append(found.scope_key)
    return tools, scopes


def clarification_ids(workflow: list[dict[str, Any]]) -> list[str]:
    return [step["id"] for step in workflow if step.get("needs_clarification")]


def assert_ready_for_active(workflow: list[dict[str, Any]]) -> None:
    pending = clarification_ids(workflow)
    if pending:
        raise InvalidRequest(
            "Resolve the steps marked needs_clarification before activating this skill.",
            details={"steps": pending},
        )
    for step in workflow:
        if step.get("type") == "tool" and not step.get("tool"):
            raise InvalidRequest(
                "Every tool step needs a tool before this skill can run.",
                details={"step_id": step["id"]},
            )


def match_keyword(trigger: dict[str, Any], text: str) -> bool:
    if trigger.get("type") != "keyword":
        return False
    hay = text.lower()
    return any(str(p).lower() in hay for p in trigger.get("patterns") or [] if p)
