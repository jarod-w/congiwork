"""前端需要的运行时配置。语言默认值从这里读，不硬编码（A8）。"""

from __future__ import annotations

from fastapi import APIRouter

from cogniwork.core.config import get_settings

router = APIRouter(tags=["config"])


@router.get("/config")
def public_config() -> dict[str, object]:
    settings = get_settings()
    return {
        "default_locale": settings.default_locale,
        "fallback_locale": settings.fallback_locale,
        "supported_locales": list(settings.supported_locales),
        "max_upload_bytes": settings.max_upload_bytes,
    }
