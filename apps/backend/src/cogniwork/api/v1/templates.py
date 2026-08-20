"""Cold-start templates (P0-04 §4.5 / M8)."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, Request

from cogniwork.api.deps import require_account
from cogniwork.auth.models import Account
from cogniwork.core.paths import find_config_file

router = APIRouter(prefix="/templates", tags=["templates"])


@lru_cache(maxsize=1)
def load_templates() -> list[dict[str, Any]]:
    path = find_config_file("task_templates.yaml", "COGNIWORK_TASK_TEMPLATES_PATH")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(raw.get("templates") or [])


@router.get("")
def list_templates(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, Any]:
    _ = (request, account)
    return {"templates": load_templates()}
