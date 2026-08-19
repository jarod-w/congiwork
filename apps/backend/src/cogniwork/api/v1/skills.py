"""Skill API (P0-06 §7)."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from cogniwork.api.deps import require_account
from cogniwork.api.v1.serialize import task_out
from cogniwork.auth.models import Account
from cogniwork.runtime.llm.router import RoutingRequest
from cogniwork.skill.presets import load_presets
from cogniwork.skill.service import SkillService, library_payload

router = APIRouter(prefix="/skills", tags=["skills"])


class SkillBody(BaseModel):
    name: str | None = None
    description: str | None = None
    trigger: dict[str, Any] | None = None
    input_schema: dict[str, Any] | None = None
    workflow: list[dict[str, Any]] | None = None
    status: Literal["draft", "active", "archived"] | None = None
    change_note: str | None = None
    source: str | None = None
    source_ref: dict[str, Any] | None = None


class DraftRequest(BaseModel):
    description: str | None = Field(default=None, max_length=8000)
    task_id: UUID | None = None
    preset_id: str | None = None


class RunRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False
    conversation_id: UUID | None = None


class SuggestRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def _skills(request: Request) -> SkillService:
    return request.app.state.skills


@router.get("")
def list_skills(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> dict[str, Any]:
    return {"skills": _skills(request).list(account.id, query=q, status=status)}


@router.get("/library")
def library(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    return library_payload(_skills(request), account.id)


@router.get("/presets")
def presets() -> dict[str, Any]:
    return {"presets": load_presets()}


@router.post("/draft")
def create_draft(
    request: Request,
    body: DraftRequest,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    service = _skills(request)
    if body.preset_id:
        return {"skill": service.copy_preset(account.id, body.preset_id)}
    engine = request.app.state.task_engine
    draft = service.draft(
        account.id,
        description=body.description,
        task_id=body.task_id,
        engine=engine,
        tools=getattr(request.app.state, "tools", None),
        llm=engine.router.client_for(
            RoutingRequest(
                task_intent="skill_draft",
                context_tokens=0,
                needs_vision=False,
                needs_tool_use=True,
                latency_class="interactive",
                cost_tier="economy",
            )
        ),
    )
    return {"draft": draft}


@router.post("/suggest")
def suggest(
    request: Request,
    body: SuggestRequest,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    return {"skills": _skills(request).suggest(account.id, body.text)}


@router.post("")
def save_skill(
    request: Request,
    body: SkillBody,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    payload = body.model_dump(exclude_none=True)
    if "workflow" not in payload:
        payload["workflow"] = []
    return {"skill": _skills(request).create(account.id, payload)}


@router.get("/{skill_id}")
def get_skill(
    request: Request,
    skill_id: UUID,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    return {"skill": _skills(request).get(account.id, skill_id)}


@router.patch("/{skill_id}")
def patch_skill(
    request: Request,
    skill_id: UUID,
    body: SkillBody,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    payload = body.model_dump(exclude_none=True)
    return {"skill": _skills(request).update(account.id, skill_id, payload)}


@router.delete("/{skill_id}")
def delete_skill(
    request: Request,
    skill_id: UUID,
    account: Annotated[Account, Depends(require_account)],
    hard: bool = Query(default=False),
) -> dict[str, Any]:
    return _skills(request).archive(account.id, skill_id, hard=hard)


@router.get("/{skill_id}/versions")
def versions(
    request: Request,
    skill_id: UUID,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    return {"versions": _skills(request).versions(account.id, skill_id)}


@router.post("/{skill_id}/versions/{version}/rollback")
def rollback(
    request: Request,
    skill_id: UUID,
    version: int,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    return {"skill": _skills(request).rollback(account.id, skill_id, version)}


@router.post("/{skill_id}/precheck")
def precheck(
    request: Request,
    skill_id: UUID,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    return _skills(request).precheck(account.id, skill_id)


@router.post("/{skill_id}/run")
def run_skill(
    request: Request,
    skill_id: UUID,
    body: RunRequest,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    task = _skills(request).run(
        account.id,
        skill_id,
        engine=request.app.state.task_engine,
        inputs=body.inputs,
        dry_run=body.dry_run,
        conversation_id=body.conversation_id,
    )
    return task_out(task)
