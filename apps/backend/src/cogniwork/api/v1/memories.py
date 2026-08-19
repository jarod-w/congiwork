"""Memory OS API（P0-02 §7）。"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from cogniwork.api.deps import require_account
from cogniwork.auth.models import Account
from cogniwork.core.errors import InvalidRequest
from cogniwork.memory.models import MemoryStatus, MemoryType
from cogniwork.memory.service import MemoryService, memory_out

router = APIRouter(prefix="/memories", tags=["memories"])


class CreateMemoryRequest(BaseModel):
    type: Literal["semantic", "preference"] = "semantic"
    content: str = Field(min_length=1, max_length=4000)
    summary: str | None = Field(default=None, max_length=240)
    subtype: str | None = None
    importance: int = Field(default=3, ge=1, le=5)


class PatchMemoryRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=4000)
    summary: str | None = None
    importance: int | None = Field(default=None, ge=1, le=5)


class ConfirmMemoryRequest(BaseModel):
    action: Literal["accept", "reject"]
    content: str | None = None


class SearchMemoryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


def _memory(request: Request) -> MemoryService:
    return request.app.state.memory


@router.get("/pending")
def list_pending(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    items = _memory(request).pending(account.id)
    return {"memories": [memory_out(item) for item in items]}


@router.get("/export")
def export_memories(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    return _memory(request).export(account.id)


@router.post("/search")
def search_memories(
    request: Request,
    body: SearchMemoryRequest,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    hits = _memory(request).search_debug(account.id, body.query)
    return {"hits": hits}


@router.get("")
def list_memories(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
    type: Literal["semantic", "episodic", "preference"] | None = Query(default=None),
    status: Literal["pending", "active", "superseded", "rejected"] | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    items = _memory(request).list(
        account.id,
        type=MemoryType(type) if type else None,
        status=MemoryStatus(status) if status else None,
        query=q,
        limit=limit,
        offset=offset,
    )
    return {"memories": [memory_out(item) for item in items]}


@router.post("")
def create_memory(
    request: Request,
    body: CreateMemoryRequest,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    item = _memory(request).create(
        account.id,
        type=MemoryType(body.type),
        content=body.content,
        summary=body.summary,
        subtype=body.subtype,
        importance=body.importance,
    )
    return memory_out(item)


@router.delete("")
def purge_memories(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
    scope_key: str | None = Query(default=None),
    all: bool = Query(default=False),
) -> dict[str, Any]:
    if scope_key:
        deleted = _memory(request).purge_by_scope(account.id, scope_key)
        return {"deleted": deleted, "scope_key": scope_key}
    if all:
        deleted = _memory(request).purge_all(account.id)
        return {"deleted": deleted}
    raise InvalidRequest("Pass scope_key or all=true to delete memories.")


@router.get("/{memory_id}")
def get_memory(
    request: Request,
    memory_id: UUID,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    return memory_out(_memory(request).get(account.id, memory_id))


@router.patch("/{memory_id}")
def patch_memory(
    request: Request,
    memory_id: UUID,
    body: PatchMemoryRequest,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    item = _memory(request).update(
        account.id,
        memory_id,
        content=body.content,
        importance=body.importance,
        summary=body.summary,
    )
    return memory_out(item)


@router.delete("/{memory_id}")
def delete_memory(
    request: Request,
    memory_id: UUID,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    _memory(request).delete(account.id, memory_id)
    return {"deleted": True, "id": str(memory_id)}


@router.post("/{memory_id}/confirm")
def confirm_memory(
    request: Request,
    memory_id: UUID,
    body: ConfirmMemoryRequest,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    item = _memory(request).confirm(
        account.id,
        memory_id,
        accept=body.action == "accept",
        content=body.content,
    )
    return memory_out(item)


@router.post("/{memory_id}/not-useful")
def mark_not_useful(
    request: Request,
    memory_id: UUID,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    return memory_out(_memory(request).mark_not_useful(account.id, memory_id))
