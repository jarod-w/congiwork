"""TaskEngine 门面（P0-03 §11 M1）。

API 与工作台只依赖这里。LangGraph、供应商 SDK、工具执行都藏在后面。
"""

from __future__ import annotations

import logging
import threading
from typing import Any
from uuid import UUID

from cogniwork.consent.models import ApprovalAction
from cogniwork.core.clock import now
from cogniwork.core.config import Settings, get_settings
from cogniwork.core.errors import InvalidRequest, NotFound
from cogniwork.core.ids import new_id
from cogniwork.runtime.approvals import ApprovalService, PendingToolCall
from cogniwork.runtime.events import InMemoryEventBroker
from cogniwork.runtime.graph import compile_graph
from cogniwork.runtime.llm.router import ModelRouter
from cogniwork.runtime.models import Surface, Task, TaskStatus, can_transition
from cogniwork.runtime.tools.registry import ToolRegistry, build_builtin_registry
from cogniwork.runtime.tools.router import ToolRouter

logger = logging.getLogger("cogniwork.runtime")


class TaskEngine:
    def __init__(
        self,
        *,
        store: Any,
        events: Any,
        consent: Any,
        audit: Any,
        tools: ToolRegistry | None = None,
        router: ModelRouter | None = None,
        settings: Settings | None = None,
        memory: Any | None = None,
        approvals: ApprovalService | None = None,
        profile: Any | None = None,
    ) -> None:
        self.store = store
        self.events = events or InMemoryEventBroker()
        self.settings = settings or get_settings()
        self.tools = tools or build_builtin_registry()
        self.tool_router = ToolRouter(self.tools, consent, audit)
        self.router = router or ModelRouter(self.settings)
        self.memory = memory
        self.profile = profile
        self.approvals = approvals or ApprovalService()
        self.consent = consent
        self.step_limit = self.settings.task_step_limit
        self.messages: dict[str, list] = {}
        self.used_memories: dict[str, list] = {}
        self.blocked_scopes: dict[str, str] = {}
        self.pending_calls: dict[str, PendingToolCall] = {}
        self.skill_cursors: dict[str, Any] = {}
        self.skills: Any | None = None
        self._cancel: set[str] = set()
        self._graph = compile_graph(self)
        self._lock = threading.Lock()
        self.max_concurrent = 3

    def is_cancelled(self, task_id: str) -> bool:
        return task_id in self._cancel

    def create_conversation(self, user_id: UUID, title: str | None = None):
        return self.store.create_conversation(user_id, title)

    def list_conversations(self, user_id: UUID):
        return self.store.list_conversations(user_id)

    def get_conversation(self, user_id: UUID, conversation_id: UUID):
        conv = self.store.get_conversation(user_id, conversation_id)
        if conv is None:
            raise NotFound("Conversation not found.")
        return conv

    def submit(
        self,
        *,
        user_id: UUID,
        message: str,
        file_ids: list[str] | None = None,
        conversation_id: UUID | None = None,
        surface: Surface = Surface.WEB,
        wait: bool = False,
        skill_id: UUID | None = None,
        skill_inputs: dict[str, Any] | None = None,
        dry_run: bool = False,
        nesting_depth: int = 0,
    ) -> Task:
        text = message.strip()
        if not text:
            raise InvalidRequest("Write a task before sending.")
        running = [
            item
            for item in self.store.list_tasks(user_id)
            if item.status.value in {"created", "planning", "running"}
        ]
        if len(running) >= self.max_concurrent:
            raise InvalidRequest(
                "You already have three tasks running. Wait for one to finish, or cancel one."
            )
        ids = [UUID(fid) for fid in (file_ids or [])]
        for fid in ids:
            if self.store.get_file(user_id, fid) is None:
                raise NotFound("Uploaded file not found.", details={"file_id": str(fid)})
        if conversation_id is None:
            conversation = self.store.create_conversation(user_id, _title_from(text))
        else:
            conversation = self.store.get_conversation(user_id, conversation_id)
            if conversation is None:
                raise NotFound("Conversation not found.")
        created = now()
        task_id = new_id()
        task = Task(
            id=task_id,
            user_id=user_id,
            conversation_id=conversation.id,
            title=_title_from(text),
            intent=_intent_from(text),
            status=TaskStatus.CREATED,
            surface=surface,
            skill_id=skill_id,
            input={
                "message": text,
                "file_ids": [str(i) for i in ids],
                "skill_id": str(skill_id) if skill_id else None,
                "skill_inputs": skill_inputs or {},
                "dry_run": dry_run,
                "nesting_depth": nesting_depth,
            },
            result=None,
            error=None,
            thread_id=str(task_id),
            cost_usd=0,
            token_in=0,
            token_out=0,
            started_at=None,
            ended_at=None,
            created_at=created,
            updated_at=created,
        )
        self.store.create_task(task)
        self.store.touch_conversation(conversation.id, task.title)
        self.events.publish(
            str(task.id), "task.created", title=task.title, status=task.status.value
        )
        if wait:
            self.run(task)
        else:
            thread = threading.Thread(
                target=self.run, args=(task,), daemon=True, name=f"task-{task.id}"
            )
            thread.start()
        return task

    def run(self, task: Task) -> None:
        try:
            self._graph.invoke(
                {
                    "task_id": str(task.id),
                    "user_id": str(task.user_id),
                    "iteration": 0,
                    "done": False,
                    "failed": False,
                    "cancel": False,
                    "paused": False,
                },
                # 每次运行用新 thread，避免 MemorySaver 把 resume 当成已结束的图。
                {"configurable": {"thread_id": str(new_id())}},
            )
        except Exception:
            logger.exception("task %s crashed", task.id)
            fresh = self.store.get_task(task.user_id, task.id)
            if fresh is not None and fresh.status not in {
                TaskStatus.SUCCEEDED,
                TaskStatus.CANCELLED,
                TaskStatus.FAILED,
                TaskStatus.TIMED_OUT,
            }:
                fresh.status = TaskStatus.FAILED
                fresh.error = {
                    "code": "internal_error",
                    "message": "Something went wrong. The error was recorded.",
                    "retryable": True,
                }
                fresh.ended_at = now()
                self.store.save_task(fresh)
                self.events.publish(str(fresh.id), "task.status", status=fresh.status.value)
                self.events.publish(str(fresh.id), "task.finished", status="failed")
                self.events.close(str(fresh.id))

    def get(self, user_id: UUID, task_id: UUID) -> Task:
        task = self.store.get_task(user_id, task_id)
        if task is None:
            raise NotFound("Task not found.")
        return task

    def list_tasks(self, user_id: UUID, conversation_id: UUID | None = None) -> list[Task]:
        return self.store.list_tasks(user_id, conversation_id)

    def cancel(self, user_id: UUID, task_id: UUID) -> Task:
        task = self.get(user_id, task_id)
        self._cancel.add(str(task.id))
        if can_transition(task.status, TaskStatus.CANCELLED):
            task.status = TaskStatus.CANCELLED
            task.ended_at = now()
            task.updated_at = now()
            self.store.save_task(task)
            self.events.publish(str(task.id), "task.status", status=task.status.value)
            self.events.publish(str(task.id), "task.finished", status="cancelled")
            self.events.close(str(task.id))
        return task

    def resume(self, user_id: UUID, task_id: UUID) -> Task:
        task = self.get(user_id, task_id)
        if task.status not in {TaskStatus.FAILED, TaskStatus.TIMED_OUT}:
            raise InvalidRequest("Only failed or timed-out tasks can be resumed.")
        self._cancel.discard(str(task.id))
        task.status = TaskStatus.RUNNING
        task.error = None
        task.ended_at = None
        task.updated_at = now()
        self.store.save_task(task)
        thread = threading.Thread(
            target=self.run, args=(task,), daemon=True, name=f"task-{task.id}"
        )
        thread.start()
        return task

    def resolve_approval(
        self,
        user_id: UUID,
        approval_id: UUID,
        action: ApprovalAction,
        edited: dict[str, Any] | None = None,
        surface: str = "web",
    ) -> Task:
        from cogniwork.runtime.graph import _finish_step, _set_status
        from cogniwork.runtime.llm.types import ChatMessage
        from cogniwork.runtime.models import StepStatus

        item, args = self.approvals.resolve(user_id, approval_id, action, edited)
        task = self.get(user_id, item.task_id)
        pending = self.pending_calls.get(str(task.id))
        self.events.publish(
            str(task.id),
            "approval.resolved",
            approval_id=str(item.id),
            action=action.value,
        )
        if action is ApprovalAction.ALWAYS_ALLOW_THIS_SCOPE and item.scope_key:
            spec = self.consent._registry.get(item.scope_key)
            version = spec.consent_text_version if spec else "1"
            self.consent.grant(
                user_id=str(user_id),
                scope_key=item.scope_key,
                skip_repeat_prompt=True,
                surface=surface,
                consent_text_version=version,
            )
        if action is ApprovalAction.REJECT:
            if can_transition(task.status, TaskStatus.CANCELLED):
                task.status = TaskStatus.CANCELLED
                task.ended_at = now()
                task.updated_at = now()
                self.store.save_task(task)
            self.events.publish(str(task.id), "task.status", status=task.status.value)
            self.events.publish(str(task.id), "task.finished", status="cancelled")
            self.events.close(str(task.id))
            self.pending_calls.pop(str(task.id), None)
            return task

        if pending is None:
            _set_status(self, task, TaskStatus.RUNNING)
            return task

        if pending.tool_name == "skill.approval":
            self.pending_calls.pop(str(task.id), None)
            cursor = self.skill_cursors.get(str(task.id))
            if cursor is not None and action is not ApprovalAction.REJECT:
                cursor.advance()
            _set_status(self, task, TaskStatus.RUNNING)
            thread = threading.Thread(
                target=self._continue_after_approval,
                args=(task, pending.iteration),
                daemon=True,
                name=f"task-{task.id}-resume",
            )
            thread.start()
            return task

        context = {
            "store": self.store,
            "user_id": str(task.user_id),
            "task_id": str(task.id),
            "step_id": str(pending.step_id),
            "surface": task.surface.value,
            "file_ids": task.input.get("file_ids") or [],
            "memory": self.memory,
        }
        step = next((s for s in task.steps if s.id == pending.step_id), None)
        started = now()
        if action is ApprovalAction.SKIP:
            if step is not None:
                step.status = StepStatus.SKIPPED
                self.store.save_step(step)
            self.messages.setdefault(str(task.id), []).append(
                ChatMessage(
                    "tool",
                    "The user skipped this step.",
                    tool_call_id=pending.call_id,
                    name=pending.tool_name,
                )
            )
        else:
            result = self.tool_router.execute_approved(
                user_id=str(user_id),
                name=pending.tool_name,
                arguments=args,
                context=context,
                audit_result="approved",
            )
            if step is not None:
                _finish_step(
                    self,
                    step,
                    StepStatus.SUCCEEDED if result.ok else StepStatus.FAILED,
                    None,
                    {"ok": result.ok, "keys": sorted((result.data or {}).keys())},
                    started,
                    None if result.ok else {"message": result.content},
                )
            self.messages.setdefault(str(task.id), []).append(
                ChatMessage(
                    "tool",
                    result.content,
                    tool_call_id=pending.call_id,
                    name=pending.tool_name,
                )
            )
            if action is ApprovalAction.EDIT_AND_APPROVE and self.memory is not None:
                from cogniwork.memory.extract import propose_from_edits

                edits = []
                for key, value in (edited or {}).items():
                    edits.append(
                        {
                            "field": key,
                            "before": (pending.arguments or {}).get(key),
                            "after": value,
                        }
                    )
                propose_from_edits(self.memory, user_id, edits, task.id)
        self.pending_calls.pop(str(task.id), None)
        _set_status(self, task, TaskStatus.RUNNING)
        thread = threading.Thread(
            target=self._continue_after_approval,
            args=(task, pending.iteration),
            daemon=True,
            name=f"task-{task.id}-resume",
        )
        thread.start()
        return task

    def _continue_after_approval(self, task: Task, iteration: int) -> None:
        from cogniwork.runtime.graph import _act, _after_act, _after_observe, _finalize, _observe

        state = {
            "task_id": str(task.id),
            "user_id": str(task.user_id),
            "iteration": iteration,
            "done": False,
            "failed": False,
            "cancel": False,
            "paused": False,
        }
        try:
            state = _observe(self, state)
            while True:
                if _after_observe(state) == "finalize":
                    _finalize(self, state)
                    return
                state = _act(self, state)
                nxt = _after_act(state)
                if nxt == "pause":
                    return
                if nxt == "finalize":
                    _finalize(self, state)
                    return
                state = _observe(self, state)
        except Exception:
            logger.exception("task %s failed to resume after approval", task.id)

    def context_bundle(self, user_id: UUID, task_id: UUID) -> dict[str, Any]:
        task = self.get(user_id, task_id)
        artifacts = self.store.list_artifacts(user_id, task_id)
        files = []
        for fid in task.input.get("file_ids") or []:
            uploaded = self.store.get_file(user_id, UUID(str(fid)))
            if uploaded:
                files.append(
                    {
                        "id": str(uploaded.id),
                        "filename": uploaded.filename,
                        "size_bytes": uploaded.size_bytes,
                    }
                )
        tools_used = sorted({s.title for s in task.steps if s.type.value == "tool"})
        memories = self.used_memories.get(str(task.id), [])
        pending = None
        if task.status is TaskStatus.WAITING_APPROVAL:
            req = self.approvals.store.pending_for_task(user_id, task_id)
            if req is not None:
                from cogniwork.runtime.approvals import approval_out

                pending = approval_out(req)
        scopes = sorted({s.scope_key for s in task.steps if s.scope_key})
        return {
            "memories": memories,
            "skills": self._skill_refs(task),
            "tools": tools_used,
            "scopes": [key for key in scopes if key],
            "files": files,
            "artifacts": [
                {
                    "id": str(a.id),
                    "filename": a.filename,
                    "content_type": a.content_type,
                    "size_bytes": a.size_bytes,
                    "created_at": a.created_at.isoformat(),
                }
                for a in artifacts
            ],
            "pending_approval": pending,
            "blocked_scope": self._blocked_scope_card(task),
            "profile_card": self._profile_card(user_id),
            "pending_profile": self._pending_profile(user_id, task_id),
        }

    def _profile_card(self, user_id: UUID) -> str:
        profile = getattr(self, "profile", None)
        if profile is None:
            return ""
        try:
            return profile.render_card(user_id)
        except Exception:
            return ""

    def _pending_profile(self, user_id: UUID, task_id: UUID) -> list[dict[str, Any]]:
        profile = getattr(self, "profile", None)
        if profile is None:
            return []
        active = profile.store.active_profile(user_id)
        if active is None:
            return []
        from cogniwork.profile.models import FieldStatus
        from cogniwork.profile.service import field_out

        rows = []
        for item in profile.store.list_fields(active.id, status=FieldStatus.PENDING):
            evidence = item.evidence or {}
            if str(evidence.get("task_id") or "") == str(task_id):
                rows.append(field_out(item))
        return rows[:3]

    def _blocked_scope_card(self, task: Task) -> dict[str, Any] | None:
        key = self.blocked_scopes.get(str(task.id))
        if not key:
            return None
        from cogniwork.consent.registry import get_registry

        spec = get_registry().get(key)
        if spec is None:
            return None
        copy = spec.copy_for(self.settings.default_locale, self.settings.fallback_locale)
        return {
            "key": spec.key,
            "trust_level": spec.trust_level.value,
            "risk": spec.risk.value,
            "consent_text_version": spec.consent_text_version,
            "copy": {
                "display_name": copy.display_name,
                "collects": copy.collects,
                "retention": copy.retention,
                "degraded_behavior": copy.degraded_behavior,
            },
        }

    def _skill_refs(self, task: Task) -> list[dict[str, Any]]:
        skill_id = task.skill_id or (task.input or {}).get("skill_id")
        if not skill_id or self.skills is None:
            return []
        try:
            payload = self.skills.get(task.user_id, UUID(str(skill_id)))
        except Exception:
            return []
        if isinstance(payload, dict) and "skill" in payload:
            skill = payload.get("skill")
        else:
            skill = payload
        if not isinstance(skill, dict):
            return []
        return [{"id": skill.get("id"), "name": skill.get("name"), "source": skill.get("source")}]


def _title_from(message: str) -> str:
    line = message.strip().splitlines()[0]
    return line[:80]


def _intent_from(message: str) -> str | None:
    lower = message.lower()
    if "weekly report" in lower or "周报" in message:
        return "weekly_report"
    if "report" in lower:
        return "report"
    return None
