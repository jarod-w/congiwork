from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from cogniwork.api.deps import require_account
from cogniwork.api.idempotency import fingerprint, remember, replay
from cogniwork.api.v1.serialize import task_out
from cogniwork.auth.models import Account
from cogniwork.runtime.engine import TaskEngine
from cogniwork.runtime.events import format_sse
from cogniwork.runtime.models import Surface

router = APIRouter(prefix="/tasks", tags=["tasks"])


class CreateTaskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    conversation_id: UUID | None = None
    file_ids: list[UUID] = Field(default_factory=list)
    surface: Literal["web", "desktop", "browser_ext", "api"] = "web"


def _engine(request: Request) -> TaskEngine:
    return request.app.state.task_engine


@router.get("")
def list_tasks(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
    conversation_id: UUID | None = Query(default=None),
) -> dict[str, object]:
    engine = _engine(request)
    tasks = engine.list_tasks(account.id, conversation_id)
    return {
        "tasks": [
            task_out(task, engine.store.list_artifacts(account.id, task.id)) for task in tasks
        ]
    }


@router.post("")
def create_task(
    request: Request,
    body: CreateTaskRequest,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, object]:
    body_hash = fingerprint(body.model_dump(mode="json"))
    cached = replay(request, body_hash)
    if cached is not None:
        return cached  # type: ignore[return-value]
    engine = _engine(request)
    task = engine.submit(
        user_id=account.id,
        message=body.message,
        file_ids=[str(fid) for fid in body.file_ids],
        conversation_id=body.conversation_id,
        surface=Surface(body.surface),
    )
    payload = task_out(task)
    remember(request, body_hash, 200, payload)
    return payload


@router.get("/{task_id}")
def get_task(
    request: Request,
    task_id: UUID,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, object]:
    engine = _engine(request)
    task = engine.get(account.id, task_id)
    return task_out(task, engine.store.list_artifacts(account.id, task.id))


@router.get("/{task_id}/context")
def task_context(
    request: Request,
    task_id: UUID,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, object]:
    return _engine(request).context_bundle(account.id, task_id)


@router.get("/{task_id}/events")
def task_events(
    request: Request,
    task_id: UUID,
    account: Annotated[Account, Depends(require_account)],
    from_seq: int = Query(default=0, ge=0),
) -> StreamingResponse:
    engine = _engine(request)
    engine.get(account.id, task_id)

    def generate():
        for event in engine.events.subscribe(str(task_id), from_seq):
            yield format_sse(event)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{task_id}/cancel")
def cancel_task(
    request: Request,
    task_id: UUID,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, object]:
    engine = _engine(request)
    task = engine.cancel(account.id, task_id)
    return task_out(task, engine.store.list_artifacts(account.id, task.id))


@router.post("/{task_id}/resume")
def resume_task(
    request: Request,
    task_id: UUID,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, object]:
    engine = _engine(request)
    task = engine.resume(account.id, task_id)
    return task_out(task, engine.store.list_artifacts(account.id, task.id))
