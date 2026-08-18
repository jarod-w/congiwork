"""GET /api/v1/scopes —— 前端 Scope 列表的唯一来源。

不要在 TypeScript 里复制一份（tests/guards/test_cross_language_contracts.py）。
语言从配置读取，不硬编码默认值（A8）。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from cogniwork.consent.registry import get_registry
from cogniwork.core.config import get_settings

router = APIRouter(tags=["scopes"])


@router.get("/scopes")
def list_scopes(locale: str | None = Query(default=None)) -> dict[str, object]:
    settings = get_settings()
    chosen = locale or settings.default_locale
    if chosen not in settings.supported_locales:
        chosen = settings.fallback_locale
    registry = get_registry()
    scopes: list[dict[str, object]] = []
    for spec in registry:
        copy = spec.copy_for(chosen, settings.fallback_locale)
        scopes.append(
            {
                "key": spec.key,
                "trust_level": spec.trust_level.value,
                "risk": spec.risk.value,
                "consent_text_version": spec.consent_text_version,
                "copy": {
                    "display_name": copy.display_name,
                    "collects": copy.collects,
                    "retention": copy.retention,
                    "degraded_behavior": copy.degraded_behavior,
                },
                "requires_os_permission": list(spec.requires_os_permission),
                "third_party_scopes": list(spec.third_party_scopes),
            }
        )
    return {"locale": chosen, "scopes": scopes}
