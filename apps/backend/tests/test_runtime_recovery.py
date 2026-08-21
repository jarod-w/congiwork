"""持久化与恢复（P0-03 RT-5、§12 验收 1）。

「重启后端进程，waiting_approval 的任务恢复后可正常继续」在这里是可执行的：
第二个 TaskEngine 代表重启后的进程 —— 它与第一个共用存储，但不共用任何
进程内状态。它必须能从存储里认出「这个任务挂在哪个工具调用上」。
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from cogniwork.consent.models import ApprovalAction, Risk
from cogniwork.core.ids import new_id
from cogniwork.runtime.approvals import ApprovalService, InMemoryApprovalStore
from cogniwork.runtime.digest import InMemoryAuditLog
from cogniwork.runtime.engine import TaskEngine
from cogniwork.runtime.events import InMemoryEventBroker
from cogniwork.runtime.llm.types import LLMResult, ToolCallDelta
from cogniwork.runtime.models import TaskStatus
from cogniwork.runtime.state import InMemoryRuntimeStateStore
from cogniwork.runtime.store import InMemoryTaskStore
from cogniwork.runtime.tools.registry import ToolRegistry
from cogniwork.runtime.tools.spec import ToolResult, ToolSpec

USER = UUID("00000000-0000-7000-8000-0000000000a1")

TOOL = ToolSpec(
    name="notion.append_block",
    provider="mcp",
    description="Append a block to a Notion page",
    input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
    scope_key="tool:notion:write",
    risk=Risk.WRITE,
    preview_renderer="text",
)


class _RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def invoke(self, spec: ToolSpec, arguments: dict[str, Any], context: dict[str, Any]):
        self.calls.append(dict(arguments))
        return ToolResult(spec.name, True, "Appended.", {"id": "block-1"})


class _NeedsApproval:
    """闸门的替身。判定仍只发生在 runtime/tools/hook.py，这里只是喂它一个结果。"""

    def check(self, user_id, scope_key, risk):
        from cogniwork.consent.models import ConsentDecision

        return ConsentDecision.REQUIRE_APPROVAL

    def degraded_behavior(self, scope_key, locale, fallback):
        return "Paste the content yourself."


class _OneToolThenDone:
    vendor = "stub"
    model = "stub-local"

    def complete(self, messages, tools, *, on_delta=None):
        called = {m.name for m in messages if m.role == "tool" and m.name}
        if TOOL.name in called:
            return LLMResult(text="Added the note.", vendor=self.vendor, model=self.model)
        return LLMResult(
            text="",
            tool_calls=[
                ToolCallDelta(id=str(new_id()), name=TOOL.name, arguments={"text": "Q3 numbers"})
            ],
            vendor=self.vendor,
            model=self.model,
        )


class _Router:
    def client_for(self, request, user_id=None):
        return _OneToolThenDone()


def _engine(store, events, approvals, state_store, executor) -> TaskEngine:
    registry = ToolRegistry()
    registry.register(TOOL, executor)
    from cogniwork.runtime.tools.builtin import BUILTIN_TOOLS, BuiltinExecutor

    builtin = BuiltinExecutor()
    for spec in BUILTIN_TOOLS:
        registry.register(spec, builtin)
    return TaskEngine(
        store=store,
        events=events,
        consent=_NeedsApproval(),
        audit=InMemoryAuditLog(),
        tools=registry,
        router=_Router(),
        approvals=approvals,
        state_store=state_store,
    )


def _wait_for(store, task_id, statuses, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = store.get_task(USER, task_id)
        if task is not None and task.status in statuses:
            return task
        time.sleep(0.02)
        continue
    return store.get_task(USER, task_id)


def test_waiting_approval_survives_a_process_restart():
    store = InMemoryTaskStore()
    events = InMemoryEventBroker()
    approvals = ApprovalService(InMemoryApprovalStore())
    state_store = InMemoryRuntimeStateStore()
    executor = _RecordingExecutor()

    first = _engine(store, events, approvals, state_store, executor)
    task = first.submit(user_id=USER, message="Add the Q3 numbers to the launch page", wait=True)
    assert store.get_task(USER, task.id).status is TaskStatus.WAITING_APPROVAL
    pending = approvals.store.pending_for_task(USER, task.id)
    assert pending is not None

    # ── 这里是「重启」：新进程，新 engine，什么进程内状态都没继承 ──
    second = _engine(store, events, approvals, state_store, _RecordingExecutor())
    assert second is not first
    assert second.pending_calls.get(str(task.id)) is not None, (
        "重启后 Runtime 必须还知道任务挂在哪个工具调用上（P0-03 §12 验收 1）"
    )
    assert second.messages[str(task.id)], "重启后消息历史必须还在，否则批准之后无法继续"

    second.resolve_approval(USER, pending.id, ApprovalAction.APPROVE)
    finished = _wait_for(store, task.id, {TaskStatus.SUCCEEDED, TaskStatus.FAILED})
    assert finished.status is TaskStatus.SUCCEEDED
    # 参数从存储里读回来，不是重新猜的
    approved = second.tool_router._registry.get(TOOL.name)[1]
    assert approved.calls == [{"text": "Q3 numbers"}]


def test_thread_id_is_stable_so_a_crash_can_resume_from_the_checkpoint():
    """RT-5：thread_id 跟着 task 走。每次 invoke 换新 thread 等于没有 checkpoint。"""
    store = InMemoryTaskStore()
    engine = _engine(
        store,
        InMemoryEventBroker(),
        ApprovalService(InMemoryApprovalStore()),
        InMemoryRuntimeStateStore(),
        _RecordingExecutor(),
    )
    task = engine.submit(user_id=USER, message="Add a note to the page", wait=True)
    assert task.thread_id == str(task.id)
    saved = store.get_task(USER, task.id)
    assert saved.thread_id == str(task.id)


def test_finished_tasks_keep_the_transparency_data_but_drop_the_transcript():
    """终态后「凭什么」面板还要 used_memories，消息历史没人读 —— 留着只是暴露面。"""
    store = InMemoryTaskStore()
    state_store = InMemoryRuntimeStateStore()
    engine = _engine(
        store,
        InMemoryEventBroker(),
        ApprovalService(InMemoryApprovalStore()),
        state_store,
        _RecordingExecutor(),
    )
    task = engine.submit(user_id=USER, message="Say hello", wait=True)
    pending = engine.approvals.store.pending_for_task(USER, task.id)
    engine.resolve_approval(USER, pending.id, ApprovalAction.SKIP)
    _wait_for(store, task.id, {TaskStatus.SUCCEEDED, TaskStatus.FAILED})

    payload = state_store.load(str(task.id))
    assert payload is not None
    assert payload["messages"] == []
    assert payload["pending_call"] is None
    assert "used_memories" in payload


def test_state_cache_is_bounded_and_eviction_loses_nothing():
    """有界 LRU 不能变成「写丢了」。

    工作台读历史任务的「凭什么」面板也会经过 registry，所以缓存必须有界。
    代价是一个还在跑的任务的条目可能在两次 append 之间被淘汰 —— 那一次 append
    必须仍然落库，否则这就是一个只在高并发下出现的丢上下文缺陷。
    """
    from cogniwork.runtime.llm.types import ChatMessage
    from cogniwork.runtime.state import InMemoryRuntimeStateStore, RuntimeStateRegistry

    store = InMemoryRuntimeStateStore()
    registry = RuntimeStateRegistry(store, cache_size=8)
    registry.messages["task-a"] = [ChatMessage("system", "start")]
    held = registry.messages["task-a"]

    # 把 task-a 挤出缓存
    for i in range(40):
        registry.messages[f"filler-{i}"] = [ChatMessage("user", str(i))]
    assert len(registry._cache) <= 8

    # 拿着淘汰前的列表对象继续 append —— 这一条必须还在存储里
    held.append(ChatMessage("assistant", "after eviction"))
    payload = store.load("task-a")
    assert [row["content"] for row in payload["messages"]] == ["start", "after eviction"]
    assert [m.content for m in registry.messages["task-a"]] == ["start", "after eviction"]
