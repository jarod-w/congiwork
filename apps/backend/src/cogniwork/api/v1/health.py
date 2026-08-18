from __future__ import annotations

from fastapi import APIRouter, Request

from cogniwork.consent.registry import get_registry
from cogniwork.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict[str, object]:
    settings = get_settings()
    registry = get_registry()
    return {
        "status": "ok",
        "version": request.app.version,
        "scopes_registered": len(registry),
        "default_locale": settings.default_locale,
        "store": settings.store_backend,
    }
