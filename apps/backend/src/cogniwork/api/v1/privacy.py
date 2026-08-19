"""隐私中心 API（P0-07 §9 / M4 / M5）。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from cogniwork.api.deps import require_account
from cogniwork.auth.models import Account
from cogniwork.core.config import get_settings
from cogniwork.memory.settings import settings_out, update_settings
from cogniwork.privacy import delete_account_data, export_user, list_audit, privacy_overview

router = APIRouter(prefix="/privacy", tags=["privacy"])


class SettingsPatch(BaseModel):
    episodic_auto_cleanup: bool | None = None
    episodic_retention_months: int | None = None


@router.get("")
def overview(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    settings = get_settings()
    return privacy_overview(
        user_id=account.id,
        consent_store=request.app.state.consent_store,
        memory=request.app.state.memory,
        task_store=request.app.state.task_store,
        settings_store=request.app.state.settings_store,
        registry=request.app.state.scope_registry,
        locale=settings.default_locale,
        fallback=settings.fallback_locale,
    )


@router.get("/audit")
def audit_log(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    rows = list_audit(request.app.state.audit_log, str(account.id), limit)
    return {"events": rows}


@router.get("/export")
def export_all(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    return export_user(
        user_id=account.id,
        email=account.email,
        memory=request.app.state.memory,
        task_store=request.app.state.task_store,
        consent_store=request.app.state.consent_store,
        audit=request.app.state.audit_log,
        settings_store=request.app.state.settings_store,
        profile=getattr(request.app.state, "profile", None),
        tools=getattr(request.app.state, "tools", None),
    )


@router.get("/settings")
def get_settings_view(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    return settings_out(request.app.state.settings_store.get(account.id))


@router.patch("/settings")
def patch_settings(
    request: Request,
    body: SettingsPatch,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    return settings_out(
        update_settings(
            request.app.state.settings_store,
            account.id,
            episodic_auto_cleanup=body.episodic_auto_cleanup,
            episodic_retention_months=body.episodic_retention_months,
        )
    )


@router.delete("/account")
def delete_account(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    return delete_account_data(
        user_id=account.id,
        memory=request.app.state.memory,
        task_store=request.app.state.task_store,
        settings_store=request.app.state.settings_store,
        approval_store=request.app.state.approvals.store
        if hasattr(request.app.state, "approvals")
        else request.app.state.task_engine.approvals.store,
        audit=request.app.state.audit_log,
        consent_store=request.app.state.consent_store,
        account_store=request.app.state.account_store,
        profile=getattr(request.app.state, "profile", None),
        tools=getattr(request.app.state, "tools", None),
    )
