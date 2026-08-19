"""Skill service: CRUD, versions, precheck, run, library (P0-06)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from cogniwork.consent.models import ConsentAction
from cogniwork.core.clock import now
from cogniwork.core.errors import InvalidRequest, NotFound
from cogniwork.core.ids import new_id
from cogniwork.runtime.models import Surface
from cogniwork.skill.draft import connected_tool_names, draft_from_text
from cogniwork.skill.from_task import draft_from_task
from cogniwork.skill.models import ProductEvent, Skill, SkillSource, SkillStatus, SkillVersion
from cogniwork.skill.presets import get_preset, load_presets
from cogniwork.skill.workflow import (
    assert_ready_for_active,
    derive_tools_and_scopes,
    match_keyword,
    normalize_input_schema,
    normalize_trigger,
    normalize_workflow,
)
from cogniwork.tools.catalog import load_catalog


class SkillService:
    def __init__(self, store: Any, *, consent_store: Any | None = None) -> None:
        self.store = store
        self.consent_store = consent_store

    def list(
        self,
        user_id: UUID,
        *,
        query: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        parsed = SkillStatus(status) if status else None
        items = self.store.list_skills(user_id, query=query, status=parsed)
        return [skill_out(item) for item in items]

    def get(self, user_id: UUID, skill_id: UUID) -> dict[str, Any]:
        return skill_out(self._require(user_id, skill_id))

    def create(
        self,
        user_id: UUID,
        body: dict[str, Any],
        *,
        source: SkillSource | None = None,
    ) -> dict[str, Any]:
        workflow = normalize_workflow(body.get("workflow"))
        tools, scopes = derive_tools_and_scopes(workflow)
        status = SkillStatus(str(body.get("status") or "draft"))
        if status is SkillStatus.ACTIVE:
            assert_ready_for_active(workflow)
        created = now()
        skill = Skill(
            id=new_id(),
            user_id=user_id,
            name=str(body.get("name") or "").strip()[:80] or "Untitled skill",
            description=str(body.get("description") or "").strip()[:2000],
            trigger=normalize_trigger(body.get("trigger")),
            input_schema=normalize_input_schema(body.get("input_schema")),
            workflow=workflow,
            tools=tools,
            required_scopes=scopes,
            source=source or SkillSource(str(body.get("source") or "manual")),
            source_ref=body.get("source_ref"),
            version=1,
            status=status,
            created_at=created,
            updated_at=created,
        )
        self.store.upsert_skill(skill)
        self._snapshot(skill, changed_by="user", note="created")
        self.record_event(
            user_id,
            "skill_created",
            {"source": skill.source.value, "skill_id": str(skill.id)},
        )
        return skill_out(skill)

    def update(self, user_id: UUID, skill_id: UUID, body: dict[str, Any]) -> dict[str, Any]:
        skill = self._require(user_id, skill_id)
        if "name" in body:
            skill.name = str(body["name"] or "").strip()[:80] or skill.name
        if "description" in body:
            skill.description = str(body["description"] or "").strip()[:2000]
        if "trigger" in body:
            skill.trigger = normalize_trigger(body["trigger"])
        if "input_schema" in body:
            skill.input_schema = normalize_input_schema(body["input_schema"])
        if "workflow" in body:
            skill.workflow = normalize_workflow(body["workflow"])
            skill.tools, skill.required_scopes = derive_tools_and_scopes(skill.workflow)
        if "status" in body:
            status = SkillStatus(str(body["status"]))
            if status is SkillStatus.ACTIVE:
                assert_ready_for_active(skill.workflow)
            skill.status = status
        skill.version += 1
        skill.updated_at = now()
        self.store.upsert_skill(skill)
        self._snapshot(skill, changed_by="user", note=str(body.get("change_note") or "updated"))
        return skill_out(skill)

    def archive(self, user_id: UUID, skill_id: UUID, *, hard: bool = False) -> dict[str, Any]:
        skill = self._require(user_id, skill_id)
        if hard:
            self.store.delete_skill(user_id, skill_id)
            return {"deleted": True, "id": str(skill_id)}
        skill.status = SkillStatus.ARCHIVED
        skill.updated_at = now()
        self.store.upsert_skill(skill)
        return skill_out(skill)

    def versions(self, user_id: UUID, skill_id: UUID) -> list[dict[str, Any]]:
        self._require(user_id, skill_id)
        return [
            {
                "version": item.version,
                "changed_by": item.changed_by,
                "change_note": item.change_note,
                "created_at": item.created_at.isoformat(),
                "snapshot": item.snapshot,
            }
            for item in self.store.list_versions(skill_id)
        ]

    def rollback(self, user_id: UUID, skill_id: UUID, version: int) -> dict[str, Any]:
        skill = self._require(user_id, skill_id)
        snap = self.store.get_version(skill_id, version)
        if snap is None:
            raise NotFound("Version not found.")
        data = snap.snapshot
        return self.update(
            user_id,
            skill_id,
            {
                "name": data.get("name", skill.name),
                "description": data.get("description", skill.description),
                "trigger": data.get("trigger", skill.trigger),
                "input_schema": data.get("input_schema", skill.input_schema),
                "workflow": data.get("workflow", skill.workflow),
                "change_note": f"rolled back to v{version}",
            },
        )

    def draft(
        self,
        user_id: UUID,
        *,
        description: str | None = None,
        task_id: UUID | None = None,
        engine: Any | None = None,
        tools: Any | None = None,
        llm: Any | None = None,
    ) -> dict[str, Any]:
        connected = connected_tool_names(tools, user_id)
        if task_id is not None:
            if engine is None:
                raise InvalidRequest("Task engine is not available.")
            task = engine.get(user_id, task_id)
            return draft_from_task(task, connected_tools=connected)
        if not description:
            raise InvalidRequest("Provide a description or a task_id.")
        return draft_from_text(description, connected_tools=connected, llm=llm)

    def copy_preset(self, user_id: UUID, preset_id: str) -> dict[str, Any]:
        preset = get_preset(preset_id)
        if preset is None:
            raise NotFound("Preset not found.")
        body = {
            "name": preset["name"],
            "description": preset["description"],
            "trigger": preset["trigger"],
            "input_schema": preset["input_schema"],
            "workflow": preset["workflow"],
            "status": "draft",
        }
        return self.create(user_id, body, source=SkillSource.PRESET_COPY)

    def precheck(self, user_id: UUID, skill_id: UUID) -> dict[str, Any]:
        skill = self._require(user_id, skill_id)
        granted = self._granted_scopes(user_id)
        missing = [key for key in skill.required_scopes if key not in granted]
        unresolved = [
            step for step in skill.workflow if step.get("type") == "tool" and not step.get("tool")
        ]
        send_candidates = _available_send_tools()
        return {
            "required_scopes": skill.required_scopes,
            "missing_scopes": missing,
            "granted_scopes": sorted(granted),
            "unresolved_tools": [
                {"step_id": step["id"], "title": step["title"], "candidates": send_candidates}
                for step in unresolved
            ],
        }

    def suggest(self, user_id: UUID, text: str) -> list[dict[str, Any]]:
        hits = []
        for skill in self.store.list_skills(user_id, status=SkillStatus.ACTIVE):
            if match_keyword(skill.trigger, text):
                hits.append(skill_out(skill))
        return hits[:5]

    def run(
        self,
        user_id: UUID,
        skill_id: UUID,
        *,
        engine: Any,
        inputs: dict[str, Any] | None = None,
        dry_run: bool = False,
        nesting_depth: int = 0,
        conversation_id: UUID | None = None,
        wait: bool = False,
    ) -> Any:
        skill = self._require(user_id, skill_id)
        if nesting_depth > 1:
            # Hard runtime limit (B8). Depth 0 is the parent; 1 is the nested
            # call. A nested skill trying to call another is depth 2.
            raise InvalidRequest(
                "Skill nesting is limited to one level. This skill tried to call another skill.",
                details={"skill_id": str(skill_id), "nesting_depth": nesting_depth},
            )
        if skill.status is SkillStatus.ARCHIVED:
            raise InvalidRequest("Archived skills cannot run.")
        if not dry_run and skill.status is not SkillStatus.ACTIVE:
            raise InvalidRequest("Activate this skill before running it.")
        if not dry_run:
            assert_ready_for_active(skill.workflow)
        message = _run_message(skill, inputs or {})
        task = engine.submit(
            user_id=user_id,
            message=message,
            conversation_id=conversation_id,
            surface=Surface.WEB,
            skill_id=skill.id,
            skill_inputs=inputs or {},
            dry_run=dry_run,
            nesting_depth=nesting_depth,
            wait=wait,
        )
        if not dry_run:
            self.record_event(
                user_id,
                "skill_reused",
                {"skill_id": str(skill.id), "source": skill.source.value},
            )
        return task

    def mark_run(self, user_id: UUID, skill_id: UUID, *, success: bool) -> None:
        skill = self.store.get_skill(user_id, skill_id)
        if skill is None:
            return
        skill.run_count += 1
        if success:
            skill.success_count += 1
        skill.last_run_at = now()
        skill.updated_at = now()
        self.store.upsert_skill(skill)

    def record_event(self, user_id: UUID, name: str, payload: dict[str, Any] | None = None) -> None:
        self.store.add_event(
            ProductEvent(
                id=new_id(),
                user_id=user_id,
                name=name,
                payload=payload or {},
                created_at=now(),
            )
        )

    def organic_reuse_count(self, user_id: UUID) -> dict[str, Any]:
        """Exit-criteria helper: preset_copy does not count (P0-06 §5.5 / §9)."""
        created = [
            row
            for row in self.store.list_events(user_id, "skill_created")
            if (row.payload or {}).get("source") in {"manual", "from_task"}
        ]
        reused_ids = {
            str((row.payload or {}).get("skill_id") or "")
            for row in self.store.list_events(user_id, "skill_reused")
        }
        organic_ids = {str((row.payload or {}).get("skill_id") or "") for row in created}
        reused_organic = [sid for sid in organic_ids if sid in reused_ids]
        return {
            "organic_created": len(created),
            "organic_reused": len(reused_organic),
            "qualifies": len(created) >= 3 and len(reused_organic) >= 1,
        }

    def l3_reached(self, user_id: UUID, registry: Any) -> bool:
        """Entered L3 = granted an L3 scope AND later had a successful execution."""
        if self.consent_store is None:
            return False
        granted_l3: set[str] = set()
        for state in self.consent_store.list_current(str(user_id)):
            if state.action is not ConsentAction.GRANTED:
                continue
            spec = registry.get(state.scope_key) if registry is not None else None
            if spec is not None and spec.trust_level.value == "L3":
                granted_l3.add(state.scope_key)
        if not granted_l3:
            return False
        for row in self.store.list_events(user_id, "scope_executed"):
            if (row.payload or {}).get("scope") in granted_l3 and (row.payload or {}).get("ok"):
                return True
        return False

    def _granted_scopes(self, user_id: UUID) -> set[str]:
        if self.consent_store is None:
            return set()
        return {
            state.scope_key
            for state in self.consent_store.list_current(str(user_id))
            if state.action is ConsentAction.GRANTED
        }

    def _require(self, user_id: UUID, skill_id: UUID) -> Skill:
        skill = self.store.get_skill(user_id, skill_id)
        if skill is None:
            raise NotFound("Skill not found.")
        return skill

    def _snapshot(self, skill: Skill, *, changed_by: str, note: str | None) -> None:
        self.store.add_version(
            SkillVersion(
                skill_id=skill.id,
                version=skill.version,
                snapshot={
                    "name": skill.name,
                    "description": skill.description,
                    "trigger": skill.trigger,
                    "input_schema": skill.input_schema,
                    "workflow": skill.workflow,
                    "tools": skill.tools,
                    "required_scopes": skill.required_scopes,
                    "status": skill.status.value,
                },
                changed_by=changed_by,
                change_note=note,
                created_at=now(),
            )
        )


def skill_out(skill: Skill) -> dict[str, Any]:
    return {
        "id": str(skill.id),
        "name": skill.name,
        "description": skill.description,
        "trigger": skill.trigger,
        "input_schema": skill.input_schema,
        "workflow": skill.workflow,
        "tools": skill.tools,
        "required_scopes": skill.required_scopes,
        "source": skill.source.value,
        "source_ref": skill.source_ref,
        "version": skill.version,
        "status": skill.status.value,
        "run_count": skill.run_count,
        "success_count": skill.success_count,
        "success_rate": skill.success_rate,
        "last_run_at": skill.last_run_at.isoformat() if skill.last_run_at else None,
        "created_at": skill.created_at.isoformat(),
        "updated_at": skill.updated_at.isoformat(),
    }


def library_payload(service: SkillService, user_id: UUID) -> dict[str, Any]:
    return {
        "skills": service.list(user_id),
        "presets": load_presets(),
        "exit_criteria": service.organic_reuse_count(user_id),
    }


def _run_message(skill: Skill, inputs: dict[str, Any]) -> str:
    bits = [f"Run skill: {skill.name}", skill.description]
    if inputs:
        bits.append("Inputs: " + ", ".join(f"{k}={v}" for k, v in inputs.items()))
    return "\n".join(bits)


def _available_send_tools() -> list[str]:
    catalog = load_catalog()
    names = []
    for provider in catalog.providers:
        for tool in provider.tools:
            if tool.risk.value == "irreversible":
                names.append(tool.name)
    return names
