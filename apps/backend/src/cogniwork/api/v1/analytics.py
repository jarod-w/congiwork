"""Product analytics events (P0-04 §9). Not user-work telemetry."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from cogniwork.api.deps import require_account
from cogniwork.auth.models import Account
from cogniwork.consent.registry import get_registry

router = APIRouter(prefix="/events", tags=["analytics"])

ALLOWED = {
    "task_created",
    "task_finished",
    "template_used",
    "authorization_prompted",
    "authorization_granted",
    "approval_resolved",
    "memory_candidate_accepted",
    "skill_created",
    "skill_reused",
    "context_panel_expanded",
    "split_proxy",
    "scope_executed",
}


class EventBody(BaseModel):
    name: str
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post("")
def record_event(
    request: Request,
    body: EventBody,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    if body.name not in ALLOWED:
        return {"recorded": False}
    request.app.state.skills.record_event(account.id, body.name, body.payload)
    return {"recorded": True}


@router.get("/exit-criteria")
def exit_criteria(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    skills = request.app.state.skills
    return {
        "organic_skills": skills.organic_reuse_count(account.id),
        "l3_reached": skills.l3_reached(account.id, get_registry()),
    }
