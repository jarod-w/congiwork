from __future__ import annotations

from fastapi import APIRouter

from .auth import router as auth_router
from .consent import router as consent_router
from .health import router as health_router
from .scopes import router as scopes_router


def build_v1_router() -> APIRouter:
    router = APIRouter()
    router.include_router(health_router)
    router.include_router(auth_router)
    router.include_router(scopes_router)
    router.include_router(consent_router)
    return router
