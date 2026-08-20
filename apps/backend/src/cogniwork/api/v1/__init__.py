from __future__ import annotations

from fastapi import APIRouter

from .analytics import router as analytics_router
from .approvals import router as approvals_router
from .auth import router as auth_router
from .config import router as config_router
from .consent import router as consent_router
from .conversations import router as conversations_router
from .files import router as files_router
from .health import router as health_router
from .llm import router as llm_router
from .memories import router as memories_router
from .privacy import router as privacy_router
from .profile import router as profile_router
from .scopes import router as scopes_router
from .skills import router as skills_router
from .tasks import router as tasks_router
from .templates import router as templates_router
from .tools import router as tools_router


def build_v1_router() -> APIRouter:
    router = APIRouter()
    router.include_router(health_router)
    router.include_router(config_router)
    router.include_router(auth_router)
    router.include_router(scopes_router)
    router.include_router(consent_router)
    router.include_router(conversations_router)
    router.include_router(tasks_router)
    router.include_router(approvals_router)
    router.include_router(files_router)
    router.include_router(memories_router)
    router.include_router(privacy_router)
    router.include_router(profile_router)
    router.include_router(tools_router)
    router.include_router(skills_router)
    router.include_router(templates_router)
    router.include_router(analytics_router)
    router.include_router(llm_router)
    return router
