"""授权 / 撤销 API（P0-07 §6.1 / §6.3）。

写入只走 store.append。运行时放行与否仍只由唯一检查点判定 ——
本模块不读决策枚举，也不做权限判断。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from cogniwork.api.deps import require_account
from cogniwork.api.idempotency import fingerprint, remember, replay
from cogniwork.auth.models import Account
from cogniwork.consent.models import ConsentAction
from cogniwork.consent.registry import get_registry
from cogniwork.consent.store import InMemoryConsentStore, PostgresConsentStore
from cogniwork.core.config import get_settings
from cogniwork.core.errors import Conflict, InvalidRequest, NotFound
from cogniwork.core.hashing import hash_ip

router = APIRouter(prefix="/consent", tags=["consent"])

Surface = Literal["web", "desktop", "browser_ext"]
ConsentStore = InMemoryConsentStore | PostgresConsentStore


class GrantConsentRequest(BaseModel):
    scope_key: str
    always_allow: bool = False
    consent_text_version: str | None = None
    surface: Surface = "web"


def _store(request: Request) -> ConsentStore:
    return request.app.state.consent_store


def _client_ip_hash(request: Request) -> str | None:
    if request.client is None or not request.client.host:
        return None
    return hash_ip(request.client.host, get_settings().ip_hash_pepper)


def _state_out(scope_key: str, action: ConsentAction, always_allow: bool) -> dict[str, Any]:
    return {
        "scope_key": scope_key,
        "action": action.value,
        "always_allow": always_allow,
    }


@router.post("")
@router.post("/")
def grant_consent(
    request: Request,
    body: GrantConsentRequest,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    body_hash = fingerprint(body.model_dump())
    cached = replay(request, body_hash)
    if cached is not None:
        return cached  # type: ignore[return-value]

    spec = get_registry().get(body.scope_key)
    if spec is None:
        raise InvalidRequest(
            "Unknown scope.",
            details={"scope_key": body.scope_key},
        )
    version = body.consent_text_version or spec.consent_text_version
    if version != spec.consent_text_version:
        raise Conflict(
            "The authorization copy has changed. Please review it again before enabling.",
            details={
                "scope_key": body.scope_key,
                "expected_version": spec.consent_text_version,
            },
        )

    user_id = str(account.id)
    _store(request).append(
        user_id=user_id,
        scope_key=body.scope_key,
        action=ConsentAction.GRANTED,
        always_allow=body.always_allow,
        surface=body.surface,
        consent_text_version=version,
        ip_hash=_client_ip_hash(request),
    )
    payload = _state_out(body.scope_key, ConsentAction.GRANTED, body.always_allow)
    remember(request, body_hash, 200, payload)
    return payload


@router.delete("/{scope_key:path}")
def revoke_consent(
    request: Request,
    scope_key: str,
    account: Annotated[Account, Depends(require_account)],
    purge_data: bool = Query(
        default=False,
        description=(
            "Whether to also delete records produced under this authorization. "
            "Default is false (B2): we ask, we do not delete unless the user chooses to."
        ),
    ),
    surface: Surface = Query(default="web"),
) -> dict[str, Any]:
    spec = get_registry().get(scope_key)
    if spec is None:
        raise InvalidRequest("Unknown scope.", details={"scope_key": scope_key})

    user_id = str(account.id)
    store = _store(request)
    current = store.current(user_id, scope_key)
    if current is None:
        raise NotFound(
            "This scope is not enabled.",
            details={"scope_key": scope_key},
        )
    if current.action is ConsentAction.GRANTED:
        store.append(
            user_id=user_id,
            scope_key=scope_key,
            action=ConsentAction.REVOKED,
            always_allow=False,
            surface=surface,
            consent_text_version=spec.consent_text_version,
            ip_hash=_client_ip_hash(request),
        )

    # Memory OS 落地后，purge_data=true 会物理删除该 Scope 写下的记忆。
    purged = 0
    if purge_data:
        memory = getattr(request.app.state, "memory", None)
        if memory is not None:
            purged = memory.purge_by_scope(account.id, scope_key)
    return {
        "scope_key": scope_key,
        "action": ConsentAction.REVOKED.value,
        "always_allow": False,
        "purge_requested": purge_data,
        "purge_completed": bool(purge_data),
        "purge_supported": True,
        "purged_memories": purged,
    }
