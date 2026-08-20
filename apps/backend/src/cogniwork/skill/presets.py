"""Built-in Skill copies (P0-06 §5.5). They belong to nobody and cannot run."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from cogniwork.core.paths import find_config_file
from cogniwork.skill.workflow import derive_tools_and_scopes, normalize_trigger, normalize_workflow


@lru_cache(maxsize=1)
def load_presets() -> list[dict[str, Any]]:
    path = find_config_file("skill_presets.yaml", "COGNIWORK_SKILL_PRESETS_PATH")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: list[dict[str, Any]] = []
    for entry in raw.get("presets") or []:
        workflow = normalize_workflow(entry["workflow"])
        tools, scopes = derive_tools_and_scopes(workflow)
        out.append(
            {
                "id": entry["id"],
                "name": entry["name"],
                "description": entry["description"],
                "trigger": normalize_trigger(entry.get("trigger")),
                "input_schema": dict(entry.get("input_schema") or {"type": "object"}),
                "workflow": workflow,
                "tools": tools,
                "required_scopes": scopes,
                "source": "preset",
                "status": "preset",
            }
        )
    return out


def get_preset(preset_id: str) -> dict[str, Any] | None:
    for item in load_presets():
        if item["id"] == preset_id:
            return item
    return None
