"""Natural-language → Skill draft (P0-06 §5.1).

The LLM is asked for forced structured output. Unknown tools become llm
steps with needs_clarification — we do not invent connectors.
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from cogniwork.core.errors import InvalidRequest
from cogniwork.runtime.llm.types import ChatMessage
from cogniwork.skill.workflow import derive_tools_and_scopes, normalize_trigger, normalize_workflow
from cogniwork.tools.catalog import load_catalog

_DRAFT_SCHEMA = {
    "name": "skill_draft",
    "description": "Structured Skill draft from a user's process description.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "parameters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "title": {"type": "string"},
                    },
                    "required": ["key"],
                },
            },
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["collect_input", "llm", "tool", "approval", "skill"],
                        },
                        "title": {"type": "string"},
                        "instruction": {"type": "string"},
                        "tool": {"type": "string"},
                        "fields": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["type", "title"],
                },
            },
        },
        "required": ["name", "description", "steps"],
    },
}


def draft_from_text(
    description: str,
    *,
    connected_tools: list[str] | None = None,
    llm: Any | None = None,
) -> dict[str, Any]:
    text = description.strip()
    if not text:
        raise InvalidRequest("Describe the process first.")
    allowed = _allowed_tools(connected_tools)
    parsed = _llm_draft(text, allowed, llm) if llm is not None else None
    if parsed is None:
        parsed = _heuristic_draft(text, allowed)
    return _finalize_draft(parsed, allowed, source="manual")


def _allowed_tools(connected: list[str] | None) -> set[str]:
    catalog = load_catalog()
    names = {tool.name for provider in catalog.providers for tool in provider.tools}
    if connected:
        extra = {name for name in connected if name in names}
        if extra:
            return extra
    return names


def _llm_draft(text: str, allowed: set[str], llm: Any) -> dict[str, Any] | None:
    tools = [
        {
            "type": "function",
            "function": {
                "name": _DRAFT_SCHEMA["name"],
                "description": _DRAFT_SCHEMA["description"],
                "parameters": _DRAFT_SCHEMA["parameters"],
            },
        }
    ]
    listing = ", ".join(sorted(allowed)) or "(none)"
    messages = [
        ChatMessage(
            "system",
            "Turn the user's process into a Skill draft. Step titles must be in "
            "the user's language, never a tool name. Only pick tools from this "
            "list: " + listing + ". If no tool fits, use type=llm and set needs_clarification. "
            "Do not invent tools.",
        ),
        ChatMessage("user", text),
    ]
    try:
        result = llm.complete(messages, tools)
    except Exception:
        return None
    if result.tool_calls:
        return result.tool_calls[0].arguments
    if result.text:
        try:
            data = json.loads(result.text)
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict):
            return data
    return None


def _heuristic_draft(text: str, allowed: set[str]) -> dict[str, Any]:
    name = text.splitlines()[0][:80]
    params = _guess_params(text)
    steps: list[dict[str, Any]] = []
    if params:
        steps.append(
            {
                "id": "s1",
                "type": "collect_input",
                "title": "Confirm the details that change each time",
                "fields": [p["key"] for p in params],
            }
        )
    read_tool = _pick_tool(text, allowed, read=True)
    if read_tool:
        steps.append(
            {
                "id": f"s{len(steps) + 1}",
                "type": "tool",
                "title": "Pull the numbers this process needs",
                "tool": read_tool,
                "on_error": "ask_user",
            }
        )
    else:
        steps.append(
            {
                "id": f"s{len(steps) + 1}",
                "type": "llm",
                "title": "Work through the uploaded or pasted material",
                "instruction": text,
                "needs_clarification": _needs_external_source(text),
            }
        )
    steps.append(
        {
            "id": f"s{len(steps) + 1}",
            "type": "llm",
            "title": "Turn the material into the deliverable",
            "instruction": (
                "Produce the deliverable the user described. Prefer a table plus "
                "short takeaways. Do not invent numbers that were not provided."
            ),
        }
    )
    steps.append(
        {
            "id": f"s{len(steps) + 1}",
            "type": "approval",
            "title": "Let me confirm before anything is sent or saved as final",
            "preview_from": steps[-1]["id"],
        }
    )
    if _looks_like_send(text):
        send_tool = _pick_tool(text, allowed, send=True)
        step: dict[str, Any] = {
            "id": f"s{len(steps) + 1}",
            "type": "tool",
            "title": "Send it to the people who need it",
            "on_error": "stop",
        }
        if send_tool:
            step["tool"] = send_tool
        else:
            step["tool"] = None
            step["needs_clarification"] = True
        steps.append(step)
    return {
        "name": name,
        "description": text[:400],
        "parameters": params,
        "steps": steps,
    }


def _finalize_draft(parsed: dict[str, Any], allowed: set[str], *, source: str) -> dict[str, Any]:
    raw_steps = parsed.get("steps") or parsed.get("workflow") or []
    cleaned: list[dict[str, Any]] = []
    for index, item in enumerate(raw_steps, start=1):
        step = dict(item)
        step.setdefault("id", f"s{index}")
        if step.get("type") == "tool":
            tool = step.get("tool")
            if tool and tool not in allowed:
                step = {
                    "id": step["id"],
                    "type": "llm",
                    "title": step.get("title") or "Work this step without an external tool",
                    "instruction": step.get("instruction") or step.get("title") or "",
                    "needs_clarification": True,
                }
        cleaned.append(step)
    workflow = normalize_workflow(cleaned)
    tools, scopes = derive_tools_and_scopes(workflow)
    params = parsed.get("parameters") or []
    properties = {}
    required = []
    for item in params:
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        properties[key] = {"type": "string", "title": item.get("title") or key}
        required.append(key)
    if not properties:
        for step in workflow:
            if step.get("type") == "collect_input":
                for key in step.get("fields") or []:
                    properties[key] = {"type": "string", "title": key}
                    required.append(key)
    schema = {
        "type": "object",
        "properties": properties,
        "required": required,
    }
    return {
        "name": str(parsed.get("name") or "Untitled skill")[:80],
        "description": str(parsed.get("description") or "")[:1000],
        "trigger": normalize_trigger(parsed.get("trigger")),
        "input_schema": schema,
        "workflow": workflow,
        "tools": tools,
        "required_scopes": scopes,
        "source": source,
        "status": "draft",
        "needs_clarification": [s["id"] for s in workflow if s.get("needs_clarification")],
    }


def _guess_params(text: str) -> list[dict[str, str]]:
    keys: list[dict[str, str]] = []
    lowered = text.lower()
    if "quarter" in lowered or "季度" in text:
        keys.append({"key": "quarter", "title": "Quarter"})
    if "channel" in lowered or "渠道" in text:
        keys.append({"key": "channels", "title": "Channels"})
    if "week" in lowered or "周" in text:
        keys.append({"key": "period", "title": "Period"})
    return keys[:6]


def _needs_external_source(text: str) -> bool:
    markers = ("pull", "from ", "connect", "拉取", "数据库")
    return any(token in text.lower() or token in text for token in markers)


def _looks_like_send(text: str) -> bool:
    return bool(re.search(r"\b(send|email|mail|share)\b", text, re.I) or "发" in text)


def _pick_tool(
    text: str, allowed: set[str], *, read: bool = False, send: bool = False
) -> str | None:
    catalog = load_catalog()
    lowered = text.lower()
    for provider in catalog.providers:
        for tool in provider.tools:
            if tool.name not in allowed:
                continue
            if send and tool.risk.value == "irreversible":
                return tool.name
            if read and tool.risk.value == "read" and provider.id in lowered:
                return tool.name
    if read:
        for name in allowed:
            found = catalog.tool(name)
            if found and found.risk.value == "read":
                # Do not pick a connector just because it exists — only if the
                # user named a source. Leaving this None is the honest path.
                return None
    return None


def connected_tool_names(tools: Any, user_id: UUID) -> list[str]:
    if tools is None:
        return []
    names: list[str] = []
    catalog = load_catalog()
    try:
        connections = tools.list_connections(user_id)
    except Exception:
        return []
    live = {row.get("provider") for row in connections if row.get("status") == "active"}
    for provider in catalog.providers:
        if provider.id not in live:
            continue
        for tool in provider.tools:
            names.append(tool.name)
    return names
