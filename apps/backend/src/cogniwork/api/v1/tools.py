"""Tool connection + OAuth API (P0-05 §7)."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from cogniwork.api.deps import require_account
from cogniwork.auth.models import Account
from cogniwork.core.config import get_settings
from cogniwork.tools.service import ToolService

router = APIRouter(prefix="/tools", tags=["tools"])


class ConnectRequest(BaseModel):
    provider: str
    scopes: list[str] | None = None
    surface: str = "web"


class PatchConnectionRequest(BaseModel):
    scopes: list[str] = Field(min_length=1)


def _tools(request: Request) -> ToolService:
    return request.app.state.tools


@router.get("/providers")
def list_providers(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    settings = get_settings()
    return {
        "providers": _tools(request).providers(settings.default_locale, settings.fallback_locale)
    }


@router.get("/connections")
def list_connections(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    return {"connections": _tools(request).list_connections(account.id)}


@router.post("/connections")
def start_connection(
    request: Request,
    body: ConnectRequest,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    return _tools(request).start_connect(
        account.id, body.provider, body.scopes, surface=body.surface
    )


@router.get("/oauth/callback")
def oauth_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
) -> Any:
    connection = _tools(request).oauth_callback(code=code, state=state)
    settings = get_settings()
    origin = settings.cors_origins[0] if settings.cors_origins else settings.public_base_url
    return RedirectResponse(f"{origin}/?connected={connection.provider}")


@router.patch("/connections/{connection_id}")
def patch_connection(
    request: Request,
    connection_id: UUID,
    body: PatchConnectionRequest,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    return _tools(request).patch_scopes(account.id, connection_id, body.scopes)


@router.delete("/connections/{connection_id}")
def delete_connection(
    request: Request,
    connection_id: UUID,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    _tools(request).disconnect(account.id, connection_id)
    return {"deleted": True, "id": str(connection_id)}


@router.get("/connections/{connection_id}/activity")
def connection_activity(
    request: Request,
    connection_id: UUID,
    account: Annotated[Account, Depends(require_account)],
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    rows = _tools(request).activity(account.id, connection_id, limit=limit)
    return {"events": rows}
