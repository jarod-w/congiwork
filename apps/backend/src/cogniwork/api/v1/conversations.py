from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from cogniwork.api.deps import require_account
from cogniwork.api.idempotency import fingerprint, remember, replay
from cogniwork.api.v1.serialize import conversation_out
from cogniwork.auth.models import Account
from cogniwork.runtime.engine import TaskEngine

router = APIRouter(prefix="/conversations", tags=["conversations"])


class CreateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)


def _engine(request: Request) -> TaskEngine:
    return request.app.state.task_engine


@router.get("")
def list_conversations(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, object]:
    items = _engine(request).list_conversations(account.id)
    return {"conversations": [conversation_out(item) for item in items]}


@router.post("")
def create_conversation(
    request: Request,
    body: CreateConversationRequest,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, object]:
    body_hash = fingerprint(body.model_dump())
    cached = replay(request, body_hash)
    if cached is not None:
        return cached  # type: ignore[return-value]
    conversation = _engine(request).create_conversation(account.id, body.title)
    payload = conversation_out(conversation)
    remember(request, body_hash, 200, payload)
    return payload


@router.get("/{conversation_id}/tasks")
def list_conversation_tasks(
    request: Request,
    conversation_id: UUID,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, object]:
    from cogniwork.api.v1.serialize import task_out

    engine = _engine(request)
    engine.get_conversation(account.id, conversation_id)
    tasks = engine.list_tasks(account.id, conversation_id)
    return {
        "tasks": [
            task_out(task, engine.store.list_artifacts(account.id, task.id)) for task in tasks
        ]
    }
