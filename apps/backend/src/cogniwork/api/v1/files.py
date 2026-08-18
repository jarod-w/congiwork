"""上传文件。Web 端每次显式选择，属 L1，不加 Scope（00-conventions.md §3）。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response

from cogniwork.api.deps import require_account
from cogniwork.api.v1.serialize import artifact_meta, file_meta
from cogniwork.auth.models import Account
from cogniwork.core.clock import now
from cogniwork.core.config import get_settings
from cogniwork.core.errors import InvalidRequest, NotFound
from cogniwork.core.ids import new_id
from cogniwork.runtime.engine import TaskEngine
from cogniwork.runtime.models import UploadedFile

router = APIRouter(tags=["files"])

_ALLOWED_SUFFIXES = {".xlsx", ".csv", ".txt", ".md", ".json"}


def _engine(request: Request) -> TaskEngine:
    return request.app.state.task_engine


@router.post("/files")
def upload_file(
    request: Request,
    account: Annotated[Account, Depends(require_account)],
    file: UploadFile = File(...),
    persist_raw: str = Form(default="false"),
) -> dict[str, object]:
    persist = persist_raw.strip().lower() in {"1", "true", "yes", "on"}
    settings = get_settings()
    filename = file.filename or "upload.bin"
    suffix = _suffix(filename)
    if suffix not in _ALLOWED_SUFFIXES:
        raise InvalidRequest(
            "This format is not supported yet. Use xlsx, csv, txt, md, or json.",
            details={"filename": filename},
        )
    payload = file.file.read()
    if len(payload) > settings.max_upload_bytes:
        raise InvalidRequest(
            "This file is larger than the upload limit.",
            details={"max_bytes": settings.max_upload_bytes},
        )
    uploaded = UploadedFile(
        id=new_id(),
        user_id=account.id,
        filename=filename,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(payload),
        persist=persist,
        content=payload,
        created_at=now(),
    )
    _engine(request).store.put_file(uploaded)
    return file_meta(uploaded)


@router.get("/artifacts/{artifact_id}")
def download_artifact(
    request: Request,
    artifact_id: UUID,
    account: Annotated[Account, Depends(require_account)],
) -> Response:
    artifact = _engine(request).store.get_artifact(account.id, artifact_id)
    if artifact is None:
        raise NotFound("Artifact not found.")
    return Response(
        content=artifact.content,
        media_type=artifact.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "X-Artifact-Filename": artifact.filename,
        },
    )


@router.get("/artifacts/{artifact_id}/meta")
def artifact_info(
    request: Request,
    artifact_id: UUID,
    account: Annotated[Account, Depends(require_account)],
) -> dict[str, object]:
    artifact = _engine(request).store.get_artifact(account.id, artifact_id)
    if artifact is None:
        raise NotFound("Artifact not found.")
    return artifact_meta(artifact)


def _suffix(filename: str) -> str:
    if "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[1].lower()
