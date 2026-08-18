"""Task 执行期间的 SSE 事件（00-conventions.md §7）。

与 packages/shared-types/src/events.ts 是同一份词表的两种语言表述。
一致性由 tests/guards/test_cross_language_contracts.py 守护。
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from typing import Any

from cogniwork.core.clock import now

TASK_EVENTS = (
    "task.created",
    "task.status",
    "plan.updated",
    "step.started",
    "step.finished",
    "tool.call",
    "tool.result",
    "message.delta",
    "approval.requested",
    "approval.resolved",
    "artifact.created",
    "memory.candidate",
    "task.finished",
)

REDIS_STREAM_TTL_SECONDS = 60 * 60
REDIS_STREAM_MAXLEN = 10_000


def make_event(event: str, task_id: str, seq: int, **payload: Any) -> dict[str, Any]:
    body = {
        "event": event,
        "task_id": task_id,
        "ts": now().isoformat().replace("+00:00", "Z"),
        "seq": seq,
    }
    body.update(payload)
    return body


def format_sse(event: dict[str, Any]) -> str:
    name = event["event"]
    seq = event["seq"]
    return f"id: {seq}\nevent: {name}\ndata: {json.dumps(event, default=str)}\n\n"


class InMemoryEventBroker:
    """进程内事件流。单测与无 Redis 的本地启动用。"""

    def __init__(self) -> None:
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._cv: dict[str, threading.Condition] = {}
        self._closed: set[str] = set()
        self._lock = threading.Lock()

    def _condition(self, task_id: str) -> threading.Condition:
        with self._lock:
            if task_id not in self._cv:
                self._cv[task_id] = threading.Condition()
            return self._cv[task_id]

    def publish(self, task_id: str, event: str, **payload: Any) -> dict[str, Any]:
        cv = self._condition(task_id)
        with cv:
            bucket = self._events.setdefault(task_id, [])
            seq = len(bucket) + 1
            body = make_event(event, task_id, seq, **payload)
            bucket.append(body)
            cv.notify_all()
            return body

    def replay(self, task_id: str, from_seq: int = 0) -> list[dict[str, Any]]:
        return [e for e in self._events.get(task_id, []) if e["seq"] > from_seq]

    def close(self, task_id: str) -> None:
        cv = self._condition(task_id)
        with cv:
            self._closed.add(task_id)
            cv.notify_all()

    def is_closed(self, task_id: str) -> bool:
        return task_id in self._closed

    def subscribe(self, task_id: str, from_seq: int = 0) -> Iterator[dict[str, Any]]:
        """阻塞迭代新事件。任务结束后再吐完缓冲就停。"""
        last = from_seq
        cv = self._condition(task_id)
        while True:
            with cv:
                pending = [e for e in self._events.get(task_id, []) if e["seq"] > last]
                if pending:
                    pass
                elif task_id in self._closed:
                    return
                else:
                    cv.wait(timeout=15)
                    continue
            for event in pending:
                last = event["seq"]
                yield event

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._cv.clear()
            self._closed.clear()


class RedisEventBroker:
    """Redis Stream，保留 1 小时，供断线补发（P0-03 §10）。"""

    def __init__(self, redis: Any, fallback: InMemoryEventBroker) -> None:
        self._redis = redis
        self._fallback = fallback

    def _key(self, task_id: str) -> str:
        return f"task:{task_id}:events"

    def publish(self, task_id: str, event: str, **payload: Any) -> dict[str, Any]:
        body = self._fallback.publish(task_id, event, **payload)
        try:
            self._redis.xadd(
                self._key(task_id),
                {"payload": json.dumps(body, default=str)},
                maxlen=REDIS_STREAM_MAXLEN,
                approximate=True,
            )
            self._redis.expire(self._key(task_id), REDIS_STREAM_TTL_SECONDS)
        except Exception:
            # Redis 挂了事件仍在进程内，SSE 本连接还能用；重连才可能丢。
            pass
        return body

    def replay(self, task_id: str, from_seq: int = 0) -> list[dict[str, Any]]:
        local = self._fallback.replay(task_id, from_seq)
        if local:
            return local
        try:
            entries = self._redis.xrange(self._key(task_id))
        except Exception:
            return []
        recovered: list[dict[str, Any]] = []
        for _eid, fields in entries:
            raw = fields.get("payload")
            if not raw:
                continue
            event = json.loads(raw)
            if event["seq"] > from_seq:
                recovered.append(event)
        return recovered

    def close(self, task_id: str) -> None:
        self._fallback.close(task_id)

    def is_closed(self, task_id: str) -> bool:
        return self._fallback.is_closed(task_id)

    def subscribe(self, task_id: str, from_seq: int = 0) -> Iterator[dict[str, Any]]:
        yield from self._fallback.subscribe(task_id, from_seq)

    def clear(self) -> None:
        self._fallback.clear()
