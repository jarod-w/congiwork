"""Personal Profile API (P0-01 §6)."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from cogniwork.api.deps import require_account
from cogniwork.auth.models import Account
from cogniwork.profile.models import FieldSource
from cogniwork.profile.service import ProfileService, field_out

router = APIRouter(prefix="/profile", tags=["profile"])


class PatchFieldRequest(BaseModel):
    value: Any


class ConfirmFieldRequest(BaseModel):
    action: Literal["accept", "reject", "edit"]
    value: Any | None = None


class InterviewAnswerRequest(BaseModel):
    text: str | None = Field(default=None, max_length=2000)
    selected: list[str] = Field(default_factory=list)


class SkipInterviewRequest(BaseModel):
    scope: Literal["question", "round", "all"] = "all"


class ArchiveRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


def _profile(request: Request) -> ProfileService:
    return request.app.state.profile


@router.get("")
def get_profile(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    return _profile(request).get(account.id, include_archived=True)


@router.get("/export")
def export_profile(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    return _profile(request).export(account.id)


@router.delete("")
def delete_profile(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    deleted = _profile(request).purge(account.id)
    return {"deleted": deleted}


@router.post("/archive")
def archive_profile(
    request: Request,
    body: ArchiveRequest,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    profile = _profile(request).archive(account.id, body.reason)
    return {"profile": {"id": str(profile.id), "version": profile.version}}


@router.patch("/fields/{key:path}")
def patch_field(
    request: Request,
    key: str,
    body: PatchFieldRequest,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    item = _profile(request).upsert_field(
        account.id,
        key,
        body.value,
        source=FieldSource.MANUAL,
    )
    return field_out(item)


@router.delete("/fields/{key:path}")
def delete_field(
    request: Request,
    key: str,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    _profile(request).delete_field(account.id, key)
    return {"deleted": True, "key": key}


@router.post("/fields/{field_id}/confirm")
def confirm_field(
    request: Request,
    field_id: UUID,
    body: ConfirmFieldRequest,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    item = _profile(request).confirm(account.id, field_id, action=body.action, value=body.value)
    return field_out(item)


@router.post("/interview/start")
def start_interview(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    return _profile(request).start_interview(account.id)


@router.post("/interview/answer")
def answer_interview(
    request: Request,
    body: InterviewAnswerRequest,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    service = _profile(request)
    result = service.answer_interview(account.id, text=body.text, selected=body.selected)
    create = result.get("create_task")
    if create and create.get("message"):
        engine = request.app.state.task_engine
        task = engine.submit(user_id=account.id, message=str(create["message"]))
        result["task"] = {"id": str(task.id), "title": task.title}
    return result


@router.post("/interview/skip")
def skip_interview(
    request: Request,
    body: SkipInterviewRequest,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    return _profile(request).skip_interview(account.id, scope=body.scope)


@router.post("/interview/complete")
def complete_interview(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    return _profile(request).complete_interview(account.id)
