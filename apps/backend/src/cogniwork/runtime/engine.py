"""TaskEngine 门面（P0-03 §11 M1）。

API 与工作台只依赖这里。LangGraph、供应商 SDK、工具执行都藏在后面。
"""

from __future__ import annotations

import logging
import threading
from typing import Any
from uuid import UUID

from cogniwork.core.clock import now
from cogniwork.core.config import Settings, get_settings
from cogniwork.core.errors import InvalidRequest, NotFound
from cogniwork.core.ids import new_id
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
    ) -> None:
        self.store = store
        self.events = events or InMemoryEventBroker()
        self.settings = settings or get_settings()
        self.tools = tools or build_builtin_registry()
        self.tool_router = ToolRouter(self.tools, consent, audit)
        self.router = router or ModelRouter(self.settings)
        self.step_limit = self.settings.task_step_limit
        self.messages: dict[str, list] = {}
        self._cancel: set[str] = set()
        self._graph = compile_graph(self)
        self._lock = threading.Lock()

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
    ) -> Task:
        text = message.strip()
        if not text:
            raise InvalidRequest("Write a task before sending.")
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
            skill_id=None,
            input={"message": text, "file_ids": [str(i) for i in ids]},
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
        return {
            "memories": [],
            "skills": [],
            "tools": tools_used,
            "scopes": [],
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
        }


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
