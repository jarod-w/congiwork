"""任务运行态的落库（P0-03 RT-5、§12 验收 1）。

LangGraph 的 checkpointer 只管图状态（当前节点 + 那几个布尔位）。真正的
上下文在别处：消息历史、本次用到的记忆、被闸门拦下的 Scope、挂起的工具调用、
Skill 游标。这些原先是 TaskEngine 上的进程内 dict。

进程内放不住的理由不是「不够优雅」，是**审批可以等 24 小时**
（`approvals.APPROVAL_TTL`）。期间重启一次后端，用户回来点「批准」，
Runtime 已经不知道该执行什么了 —— `P0-03` §12 验收 1 要的正是这条不许发生。

保留期：任务进终态时 `_finalize` 调 `finish`，扔掉执行用的那部分（消息历史、
挂起调用、Skill 游标），留下工作台还要显示的（`used_memories`、被拦下的 Scope）。
这份数据含任务正文，与 `execution_audit` 不是一回事（后者受硬约束 8 约束、
只记「做了什么」），它就是用户自己的任务上下文，跟着 task 行一起被物理删除。
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from psycopg.types.json import Json

from cogniwork.core.clock import now
from cogniwork.runtime.approvals import PendingToolCall
from cogniwork.runtime.llm.types import ChatMessage

# 进程内缓存的条目数上限。够放下并发在跑的任务 + 用户正在翻的几个历史任务。
CACHE_SIZE = 256


@dataclass
class TaskRuntimeState:
    """一个任务在执行期间的全部进程外可见状态。"""

    task_id: str
    messages: list[ChatMessage] = field(default_factory=list)
    used_memories: list[dict[str, Any]] = field(default_factory=list)
    blocked_scope: str | None = None
    pending_call: PendingToolCall | None = None
    skill_cursor: Any | None = None
    economy_notice_sent: bool = False


def dump_state(state: TaskRuntimeState) -> dict[str, Any]:
    return {
        "messages": [_dump_message(m) for m in state.messages],
        "used_memories": list(state.used_memories),
        "blocked_scope": state.blocked_scope,
        "pending_call": _dump_pending(state.pending_call),
        "skill_cursor": _dump_cursor(state.skill_cursor),
        "economy_notice_sent": bool(state.economy_notice_sent),
    }


def load_state(task_id: str, payload: dict[str, Any] | None) -> TaskRuntimeState:
    data = payload or {}
    return TaskRuntimeState(
        task_id=task_id,
        messages=[_load_message(row) for row in data.get("messages") or []],
        used_memories=list(data.get("used_memories") or []),
        blocked_scope=data.get("blocked_scope"),
        pending_call=_load_pending(data.get("pending_call")),
        skill_cursor=_load_cursor(data.get("skill_cursor")),
        economy_notice_sent=bool(data.get("economy_notice_sent")),
    )


def _dump_message(message: ChatMessage) -> dict[str, Any]:
    return {
        "role": message.role,
        "content": message.content,
        "tool_call_id": message.tool_call_id,
        "name": message.name,
    }


def _load_message(row: dict[str, Any]) -> ChatMessage:
    return ChatMessage(
        str(row.get("role") or "user"),
        str(row.get("content") or ""),
        tool_call_id=row.get("tool_call_id"),
        name=row.get("name"),
    )


def _dump_pending(call: PendingToolCall | None) -> dict[str, Any] | None:
    if call is None:
        return None
    return {
        "task_id": str(call.task_id),
        "user_id": str(call.user_id),
        "tool_name": call.tool_name,
        "arguments": call.arguments,
        "call_id": call.call_id,
        "iteration": call.iteration,
        "step_id": str(call.step_id),
        "approval_id": str(call.approval_id),
    }


def _load_pending(row: dict[str, Any] | None) -> PendingToolCall | None:
    if not row:
        return None
    return PendingToolCall(
        task_id=UUID(str(row["task_id"])),
        user_id=UUID(str(row["user_id"])),
        tool_name=str(row["tool_name"]),
        arguments=dict(row.get("arguments") or {}),
        call_id=str(row.get("call_id") or ""),
        iteration=int(row.get("iteration") or 0),
        step_id=UUID(str(row["step_id"])),
        approval_id=UUID(str(row["approval_id"])),
    )


def _dump_cursor(cursor: Any | None) -> dict[str, Any] | None:
    if cursor is None:
        return None
    return {
        "stack": [[skill, index, depth] for skill, index, depth in cursor.stack],
        "outputs": dict(cursor.outputs),
    }


def _load_cursor(row: dict[str, Any] | None) -> Any | None:
    if not row:
        return None
    # 延迟导入：skill_driver 反过来要用本模块的 registry。
    from cogniwork.runtime.skill_driver import SkillCursor

    stack = [(frame[0], int(frame[1]), int(frame[2])) for frame in row.get("stack") or []]
    if not stack:
        return None
    cursor = SkillCursor(stack[0][0], depth=stack[0][2])
    cursor.stack = stack
    cursor.outputs = dict(row.get("outputs") or {})
    return cursor


class InMemoryRuntimeStateStore:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def load(self, task_id: str) -> dict[str, Any] | None:
        return self.rows.get(task_id)

    def save(self, task_id: str, payload: dict[str, Any]) -> None:
        self.rows[task_id] = payload

    def delete(self, task_id: str) -> None:
        self.rows.pop(task_id, None)

    def task_ids(self) -> list[str]:
        return list(self.rows)

    def clear(self) -> None:
        self.rows.clear()


class PostgresRuntimeStateStore:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    def load(self, task_id: str) -> dict[str, Any] | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT payload FROM task_runtime_state WHERE task_id = %s",
                (UUID(task_id),),
            ).fetchone()
        return dict(row["payload"]) if row and row["payload"] else None

    def save(self, task_id: str, payload: dict[str, Any]) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO task_runtime_state (task_id, payload, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (task_id) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    updated_at = EXCLUDED.updated_at
                """,
                (UUID(task_id), Json(payload), now()),
            )

    def delete(self, task_id: str) -> None:
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM task_runtime_state WHERE task_id = %s", (UUID(task_id),))

    def task_ids(self) -> list[str]:
        with self._pool.connection() as conn:
            rows = conn.execute("SELECT task_id FROM task_runtime_state").fetchall()
        return [str(row["task_id"]) for row in rows]

    def clear(self) -> None:
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM task_runtime_state")


class RuntimeStateRegistry:
    """按 task_id 取运行态；读缺失时回落存储，写立刻落库。

    对外仍是五个 dict 形状的视图，调用点不变 —— 换掉的是「进程重启就没了」，
    不是 Runtime 的写法。
    """

    def __init__(self, store: Any | None = None, *, cache_size: int = CACHE_SIZE) -> None:
        self._store = store or InMemoryRuntimeStateStore()
        # 有界 LRU。工作台读一个历史任务的「凭什么」面板也会经过这里，无界的话
        # 进程活多久就攒多久。淘汰是安全的：每一次写都已经落库了，
        # 下次访问从存储读回来（见 _ListView.__getitem__ 的 write-back）。
        self._cache: OrderedDict[str, TaskRuntimeState] = OrderedDict()
        self._cache_size = max(8, cache_size)
        self._lock = threading.RLock()
        self.messages = _ListView(self, "messages")
        self.used_memories = _ListView(self, "used_memories")
        self.blocked_scopes = _ScalarView(self, "blocked_scope")
        self.pending_calls = _ScalarView(self, "pending_call")
        self.skill_cursors = _ScalarView(self, "skill_cursor")

    def entry(self, task_id: str) -> TaskRuntimeState:
        with self._lock:
            found = self._cache.get(task_id)
            if found is None:
                found = load_state(task_id, self._store.load(task_id))
                self._cache[task_id] = found
                while len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
            else:
                self._cache.move_to_end(task_id)
            return found

    def has(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self._cache:
                return True
        return self._store.load(task_id) is not None

    def flush(self, task_id: str) -> None:
        """把内存里的改动写回存储。

        列表是原地 append 的（`messages[tid].append(...)`），视图接不到那次写，
        所以图的每个节点结束时显式调一次。挂起前那一次是必须的 —— 其他都能重算，
        挂起后的上下文重算不出来。
        """
        with self._lock:
            found = self._cache.get(task_id)
            if found is None:
                return
            payload = dump_state(found)
        self._store.save(task_id, payload)

    def finish(self, task_id: str) -> None:
        """任务进终态：留下工作台还要显示的，扔掉执行用的。

        `used_memories` / `blocked_scope` 是「凭什么」面板的数据源，任务结束后
        用户还会看（`P0-04` §3）。消息历史、挂起调用、Skill 游标只有执行期间有用，
        且消息历史是这里最大的一块 —— 留着既没人读也是额外的暴露面。
        """
        with self._lock:
            entry = self._cache.get(task_id)
            if entry is None:
                entry = load_state(task_id, self._store.load(task_id))
                self._cache[task_id] = entry
            entry.messages = []
            entry.pending_call = None
            entry.skill_cursor = None
            entry.economy_notice_sent = False
        self.flush(task_id)

    def drop(self, task_id: str) -> None:
        with self._lock:
            self._cache.pop(task_id, None)
        self._store.delete(task_id)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
        if hasattr(self._store, "clear"):
            self._store.clear()

    def task_ids(self) -> list[str]:
        with self._lock:
            known = set(self._cache)
        return sorted(known | set(self._store.task_ids()))


class _FlushingList(list):
    """append 即落库。图里的消息历史是一条条追加的，不能等到节点结束。

    写回走 `_ListView.write_back` 而不是直接 `registry.flush` —— 这样即便本条目
    在两次 append 之间被 LRU 淘汰过，也是把**这个列表**重新挂回条目再落库，
    不会静默丢掉这一次 append。
    """

    def __init__(self, items: list[Any], view: _ListView, task_id: str) -> None:
        super().__init__(items)
        self._view = view
        self._task_id = task_id

    def append(self, item: Any) -> None:  # noqa: D102 - list API
        super().append(item)
        self._view.write_back(self._task_id, self)

    def extend(self, items: Any) -> None:  # noqa: D102 - list API
        super().extend(items)
        self._view.write_back(self._task_id, self)


class _ListView(MutableMapping):
    def __init__(self, registry: RuntimeStateRegistry, attr: str) -> None:
        self._registry = registry
        self._attr = attr

    def write_back(self, task_id: str, value: list[Any]) -> None:
        setattr(self._registry.entry(task_id), self._attr, value)
        self._registry.flush(task_id)

    def __getitem__(self, task_id: str) -> list[Any]:
        entry = self._registry.entry(task_id)
        current = getattr(entry, self._attr)
        if not isinstance(current, _FlushingList):
            current = _FlushingList(list(current), self, task_id)
            setattr(entry, self._attr, current)
        return current

    def __setitem__(self, task_id: str, value: list[Any]) -> None:
        self.write_back(task_id, _FlushingList(list(value), self, task_id))

    def __delitem__(self, task_id: str) -> None:
        self.write_back(task_id, _FlushingList([], self, task_id))

    def __iter__(self) -> Iterator[str]:
        for task_id in self._registry.task_ids():
            if getattr(self._registry.entry(task_id), self._attr):
                yield task_id

    def __len__(self) -> int:
        return sum(1 for _ in self.__iter__())

    # 只在测试里用（conftest 逐个视图 clear）。落到 registry 上整块清，
    # 是因为一行存储承载五个字段，单独清一个没有意义。
    def clear(self) -> None:
        self._registry.clear()


class _ScalarView(MutableMapping):
    """标量字段的 dict 视图：值为 None 时表现为「键不存在」。"""

    def __init__(self, registry: RuntimeStateRegistry, attr: str) -> None:
        self._registry = registry
        self._attr = attr

    def __getitem__(self, task_id: str) -> Any:
        value = getattr(self._registry.entry(task_id), self._attr)
        if value is None:
            raise KeyError(task_id)
        return value

    def __setitem__(self, task_id: str, value: Any) -> None:
        setattr(self._registry.entry(task_id), self._attr, value)
        self._registry.flush(task_id)

    def __delitem__(self, task_id: str) -> None:
        entry = self._registry.entry(task_id)
        if getattr(entry, self._attr) is None:
            raise KeyError(task_id)
        setattr(entry, self._attr, None)
        self._registry.flush(task_id)

    def __iter__(self) -> Iterator[str]:
        for task_id in self._registry.task_ids():
            if getattr(self._registry.entry(task_id), self._attr) is not None:
                yield task_id

    def __len__(self) -> int:
        return sum(1 for _ in self.__iter__())

    # 同 _ListView.clear：测试用，整块清。
    def clear(self) -> None:
        self._registry.clear()
