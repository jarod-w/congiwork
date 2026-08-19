"""审批中断与恢复（P0-03 §6 / §11 M4）。

闸门判定仍只发生在 runtime/tools/hook.py。本模块只保存「已经需要人看一眼」
的请求，并在用户决断后把参数交回执行链。Executor 看不到这里。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from psycopg.types.json import Json

from cogniwork.consent.models import ApprovalAction, Risk
from cogniwork.core.clock import now
from cogniwork.core.errors import InvalidRequest, NotFound
from cogniwork.core.ids import new_id
from cogniwork.runtime.tools.spec import ToolSpec

APPROVAL_TTL = timedelta(hours=24)


class ApprovalStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"


@dataclass(slots=True)
class ApprovalRequest:
    id: UUID
    user_id: UUID
    task_id: UUID
    tool_name: str
    risk: Risk
    title: str
    arguments: dict[str, Any]
    preview: dict[str, Any]
    preview_renderer: str
    status: str
    expires_at: datetime
    created_at: datetime
    step_id: UUID | None = None
    scope_key: str | None = None
    editable_fields: list[str] = field(default_factory=list)
    edited_arguments: dict[str, Any] | None = None
    resolved_at: datetime | None = None


@dataclass(slots=True)
class PendingToolCall:
    task_id: UUID
    user_id: UUID
    tool_name: str
    arguments: dict[str, Any]
    call_id: str
    iteration: int
    step_id: UUID
    approval_id: UUID


def build_preview(spec: ToolSpec | None, arguments: dict[str, Any]) -> dict[str, Any]:
    renderer = (spec.preview_renderer if spec else None) or "text"
    if renderer == "email":
        to_value = arguments.get("to") or arguments.get("recipients") or []
        if isinstance(to_value, str):
            to_list = [to_value]
        else:
            to_list = list(to_value)
        return {
            "type": "email",
            "data": {
                "to": to_list,
                "to_count": len(to_list),
                "subject": arguments.get("subject") or "",
                "body": arguments.get("body") or arguments.get("text") or "",
                "cc": arguments.get("cc") or [],
            },
        }
    if renderer == "table":
        rows = arguments.get("rows") or arguments.get("records") or []
        return {"type": "table", "data": {"rows": rows, "row_count": len(rows)}}
    if renderer == "diff":
        return {
            "type": "diff",
            "data": {
                "before": arguments.get("before") or arguments.get("original") or "",
                "after": (
                    arguments.get("after")
                    or arguments.get("updated")
                    or arguments.get("body")
                    or ""
                ),
            },
        }
    return {"type": "text", "data": {"summary": _text_preview(arguments)}}


def editable_fields_for(renderer: str) -> list[str]:
    if renderer == "email":
        return ["to", "subject", "body"]
    if renderer == "table":
        return ["rows"]
    if renderer == "diff":
        return ["after"]
    return ["body", "content"]


def approval_out(item: ApprovalRequest) -> dict[str, Any]:
    return {
        "approval_id": str(item.id),
        "task_id": str(item.task_id),
        "step_id": str(item.step_id) if item.step_id else None,
        "scope": item.scope_key,
        "risk": item.risk.value,
        "title": item.title,
        "tool_name": item.tool_name,
        "preview": item.preview,
        "editable_fields": item.editable_fields,
        "status": item.status,
        "expires_at": item.expires_at.isoformat(),
        "arguments": item.arguments,
        "created_at": item.created_at.isoformat(),
    }


class InMemoryApprovalStore:
    def __init__(self) -> None:
        self.rows: dict[UUID, ApprovalRequest] = {}

    def put(self, item: ApprovalRequest) -> ApprovalRequest:
        self.rows[item.id] = item
        return item

    def get(self, user_id: UUID, approval_id: UUID) -> ApprovalRequest | None:
        item = self.rows.get(approval_id)
        if item is None or item.user_id != user_id:
            return None
        return item

    def pending_for_task(self, user_id: UUID, task_id: UUID) -> ApprovalRequest | None:
        found = [
            item
            for item in self.rows.values()
            if item.user_id == user_id
            and item.task_id == task_id
            and item.status == ApprovalStatus.PENDING
        ]
        found.sort(key=lambda item: item.created_at, reverse=True)
        return found[0] if found else None

    def list_for_task(self, user_id: UUID, task_id: UUID) -> list[ApprovalRequest]:
        found = [
            item
            for item in self.rows.values()
            if item.user_id == user_id and item.task_id == task_id
        ]
        found.sort(key=lambda item: item.created_at, reverse=True)
        return found

    def delete_for_user(self, user_id: UUID) -> None:
        gone = [key for key, item in self.rows.items() if item.user_id == user_id]
        for key in gone:
            del self.rows[key]

    def clear(self) -> None:
        self.rows.clear()


class PostgresApprovalStore:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    def put(self, item: ApprovalRequest) -> ApprovalRequest:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO approval_request (
                    id, user_id, task_id, step_id, tool_name, scope_key, risk, title,
                    arguments, preview, preview_renderer, editable_fields, status,
                    edited_arguments, expires_at, resolved_at, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    edited_arguments = EXCLUDED.edited_arguments,
                    resolved_at = EXCLUDED.resolved_at
                """,
                (
                    item.id,
                    item.user_id,
                    item.task_id,
                    item.step_id,
                    item.tool_name,
                    item.scope_key,
                    item.risk.value,
                    item.title,
                    Json(item.arguments),
                    Json(item.preview),
                    item.preview_renderer,
                    item.editable_fields,
                    item.status,
                    Json(item.edited_arguments) if item.edited_arguments is not None else None,
                    item.expires_at,
                    item.resolved_at,
                    item.created_at,
                ),
            )
        return item

    def get(self, user_id: UUID, approval_id: UUID) -> ApprovalRequest | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM approval_request WHERE id = %s AND user_id = %s",
                (approval_id, user_id),
            ).fetchone()
        return _from_row(row) if row else None

    def pending_for_task(self, user_id: UUID, task_id: UUID) -> ApprovalRequest | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM approval_request
                WHERE user_id = %s AND task_id = %s AND status = 'pending'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id, task_id),
            ).fetchone()
        return _from_row(row) if row else None

    def list_for_task(self, user_id: UUID, task_id: UUID) -> list[ApprovalRequest]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM approval_request
                WHERE user_id = %s AND task_id = %s
                ORDER BY created_at DESC
                """,
                (user_id, task_id),
            ).fetchall()
        return [_from_row(row) for row in rows]

    def delete_for_user(self, user_id: UUID) -> None:
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM approval_request WHERE user_id = %s", (user_id,))

    def clear(self) -> None:
        with self._pool.connection() as conn:
            conn.execute("TRUNCATE approval_request")


class ApprovalService:
    def __init__(self, store: Any | None = None) -> None:
        self.store = store or InMemoryApprovalStore()

    def create(
        self,
        *,
        user_id: UUID,
        task_id: UUID,
        step_id: UUID | None,
        spec: ToolSpec | None,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ApprovalRequest:
        renderer = (spec.preview_renderer if spec else None) or "text"
        created = now()
        item = ApprovalRequest(
            id=new_id(),
            user_id=user_id,
            task_id=task_id,
            step_id=step_id,
            tool_name=tool_name,
            scope_key=spec.scope_key if spec else None,
            risk=spec.risk if spec else Risk.WRITE,
            title=_title(spec, tool_name, arguments),
            arguments=arguments,
            preview=build_preview(spec, arguments),
            preview_renderer=renderer,
            editable_fields=editable_fields_for(renderer),
            status=ApprovalStatus.PENDING,
            edited_arguments=None,
            expires_at=created + APPROVAL_TTL,
            resolved_at=None,
            created_at=created,
        )
        return self.store.put(item)

    def get(self, user_id: UUID, approval_id: UUID) -> ApprovalRequest:
        item = self.store.get(user_id, approval_id)
        if item is None:
            raise NotFound("Approval request not found.")
        return item

    def resolve(
        self,
        user_id: UUID,
        approval_id: UUID,
        action: ApprovalAction,
        edited: dict[str, Any] | None = None,
    ) -> tuple[ApprovalRequest, dict[str, Any]]:
        item = self.get(user_id, approval_id)
        if item.status != ApprovalStatus.PENDING:
            raise InvalidRequest("This approval has already been resolved.")
        if item.expires_at <= now():
            item.status = ApprovalStatus.TIMED_OUT
            item.resolved_at = now()
            self.store.put(item)
            raise InvalidRequest("This approval timed out. Restart the task to try again.")
        if action is ApprovalAction.ALWAYS_ALLOW_THIS_SCOPE and item.risk is Risk.IRREVERSIBLE:
            raise InvalidRequest(
                "This action cannot be set to skip future confirmation.",
                details={"risk": item.risk.value},
            )
        if action is ApprovalAction.REJECT:
            item.status = ApprovalStatus.REJECTED
        elif action is ApprovalAction.SKIP:
            item.status = ApprovalStatus.SKIPPED
        elif action is ApprovalAction.EDIT_AND_APPROVE:
            if not edited:
                raise InvalidRequest("Edited content is required.")
            item.edited_arguments = {**item.arguments, **edited}
            item.preview = build_preview(None, item.edited_arguments) | {
                "type": item.preview.get("type") or "text"
            }
            item.status = ApprovalStatus.EDITED
        else:
            item.status = ApprovalStatus.APPROVED
        item.resolved_at = now()
        self.store.put(item)
        args = item.edited_arguments or item.arguments
        return item, args


def _title(spec: ToolSpec | None, name: str, arguments: dict[str, Any]) -> str:
    if spec and spec.preview_renderer == "email":
        count = arguments.get("to") or arguments.get("recipients") or []
        n = len(count) if not isinstance(count, str) else 1
        return f"Send email to {n} recipient{'s' if n != 1 else ''}"
    if spec:
        return spec.description.split(".")[0]
    return name


def _text_preview(arguments: dict[str, Any]) -> str:
    for key in ("body", "content", "text", "message", "summary"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value[:2000]
    keys = ", ".join(sorted(arguments.keys())[:8])
    return f"Parameters: {keys}" if keys else "No preview available."


def _from_row(row: dict[str, Any]) -> ApprovalRequest:
    return ApprovalRequest(
        id=row["id"],
        user_id=row["user_id"],
        task_id=row["task_id"],
        step_id=row.get("step_id"),
        tool_name=row["tool_name"],
        scope_key=row.get("scope_key"),
        risk=Risk(row["risk"]),
        title=row["title"],
        arguments=row["arguments"] or {},
        preview=row["preview"] or {},
        preview_renderer=row["preview_renderer"],
        editable_fields=list(row.get("editable_fields") or []),
        status=row["status"],
        edited_arguments=row.get("edited_arguments"),
        expires_at=row["expires_at"],
        resolved_at=row.get("resolved_at"),
        created_at=row["created_at"],
    )
