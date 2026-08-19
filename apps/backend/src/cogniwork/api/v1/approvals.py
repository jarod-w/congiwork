"""审批 API（P0-03 §6）。"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from cogniwork.api.deps import require_account
from cogniwork.auth.models import Account
from cogniwork.consent.models import ApprovalAction
from cogniwork.runtime.approvals import approval_out
from cogniwork.runtime.engine import TaskEngine

router = APIRouter(tags=["approvals"])


class ResolveApprovalRequest(BaseModel):
    action: ApprovalAction
    edited: dict[str, Any] | None = None
    surface: Literal["web", "desktop", "browser_ext"] = "web"


def _engine(request: Request) -> TaskEngine:
    return request.app.state.task_engine


@router.get("/tasks/{task_id}/approval")
def get_pending_approval(
    request: Request,
    task_id: UUID,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    engine = _engine(request)
    engine.get(account.id, task_id)
    pending = engine.approvals.store.pending_for_task(account.id, task_id)
    if pending is None:
        return {"approval": None}
    return {"approval": approval_out(pending)}


@router.post("/approvals/{approval_id}/resolve")
def resolve_approval(
    request: Request,
    approval_id: UUID,
    body: ResolveApprovalRequest,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    engine = _engine(request)
    task = engine.resolve_approval(
        account.id,
        approval_id,
        ApprovalAction(body.action),
        edited=body.edited,
        surface=body.surface,
    )
    pending = engine.approvals.store.pending_for_task(account.id, task.id)
    from cogniwork.api.v1.serialize import task_out

    payload = task_out(task, engine.store.list_artifacts(account.id, task.id))
    payload["pending_approval"] = approval_out(pending) if pending else None
    return payload
