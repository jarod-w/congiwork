"""Custom LLM provider (P0-03 §7.1 / M6b)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from cogniwork.api.deps import require_account
from cogniwork.auth.models import Account
from cogniwork.core.clock import now
from cogniwork.core.config import get_settings
from cogniwork.core.errors import InvalidRequest, NotFound, PermissionDenied
from cogniwork.core.ids import new_id
from cogniwork.runtime.llm.probe import probe_provider
from cogniwork.runtime.llm.ssrf import assert_public_https
from cogniwork.skill.models import CustomLlmProvider
from cogniwork.tools.vault import normalize_master_key, open_bundle, seal_bundle

router = APIRouter(prefix="/llm", tags=["llm"])


class ProviderBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    base_url: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=120)
    api_key: str = Field(min_length=1, max_length=4000)
    unit_cost_usd: float | None = Field(default=None, ge=0)


def _custom_granted(request: Request, user_id: str) -> bool:
    store = request.app.state.consent_store
    for state in store.list_current(user_id):
        if state.scope_key == "llm:custom:route" and state.action.value == "granted":
            return True
    return False


@router.get("/custom")
def get_custom(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    provider = request.app.state.skills.store.get_provider(account.id)
    granted = _custom_granted(request, str(account.id))
    if provider is None:
        return {"provider": None, "scope_granted": granted}
    return {"provider": _out(provider), "scope_granted": granted}


@router.put("/custom")
def put_custom(
    request: Request,
    body: ProviderBody,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    if not _custom_granted(request, str(account.id)):
        raise PermissionDenied(
            "Enable sending task content to a model you configured first.",
            details={"scope_key": "llm:custom:route"},
        )
    resolved = assert_public_https(body.base_url)
    capabilities = probe_provider(resolved.safe_url, body.api_key, body.model)
    settings = get_settings()
    master = normalize_master_key(settings.vault_master_key)
    ciphertext, wrapped, version = seal_bundle({"api_key": body.api_key}, master)
    existing = request.app.state.skills.store.get_provider(account.id)
    created = now()
    provider = CustomLlmProvider(
        id=existing.id if existing else new_id(),
        user_id=account.id,
        name=body.name.strip(),
        base_url=resolved.safe_url,
        model=body.model.strip(),
        ciphertext=ciphertext,
        dek_wrapped=wrapped,
        key_version=version,
        capabilities=capabilities,
        unit_cost_usd=body.unit_cost_usd,
        status="active" if capabilities.get("tool_use") else "probe_failed",
        last_probed_at=created,
        created_at=existing.created_at if existing else created,
        updated_at=created,
    )
    request.app.state.skills.store.upsert_provider(provider)
    return {"provider": _out(provider), "scope_granted": True}


@router.delete("/custom")
def delete_custom(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    provider = request.app.state.skills.store.get_provider(account.id)
    if provider is None:
        raise NotFound("No custom provider configured.")
    provider.status = "disabled"
    provider.updated_at = now()
    request.app.state.skills.store.upsert_provider(provider)
    return {"deleted": True}


def open_api_key(provider: CustomLlmProvider) -> str:
    settings = get_settings()
    bundle = open_bundle(
        provider.ciphertext,
        provider.dek_wrapped,
        normalize_master_key(settings.vault_master_key),
    )
    key = bundle.get("api_key")
    if not key:
        raise InvalidRequest("Custom provider key is missing.")
    return str(key)


def _out(provider: CustomLlmProvider) -> dict[str, Any]:
    return {
        "id": str(provider.id),
        "name": provider.name,
        "base_url": provider.base_url,
        "model": provider.model,
        "capabilities": provider.capabilities,
        "status": provider.status,
        "unit_cost_usd": provider.unit_cost_usd,
        "last_probed_at": provider.last_probed_at.isoformat() if provider.last_probed_at else None,
        "has_key": True,
    }
