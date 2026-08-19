"""把领域对象收成 API 能返回的 JSON。不含文件正文。"""

from __future__ import annotations

from typing import Any

from cogniwork.runtime.models import Artifact, Conversation, Task, TaskStep, UploadedFile


def conversation_out(conversation: Conversation) -> dict[str, Any]:
    return {
        "id": str(conversation.id),
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }


def step_out(step: TaskStep) -> dict[str, Any]:
    return {
        "id": str(step.id),
        "seq": step.seq,
        "type": step.type.value,
        "title": step.title,
        "status": step.status.value,
        "scope_key": step.scope_key,
        "input_digest": step.input_digest,
        "output_digest": step.output_digest,
        "error": step.error,
        "duration_ms": step.duration_ms,
        "created_at": step.created_at.isoformat(),
    }


def artifact_meta(artifact: Artifact) -> dict[str, Any]:
    return {
        "id": str(artifact.id),
        "task_id": str(artifact.task_id),
        "filename": artifact.filename,
        "content_type": artifact.content_type,
        "size_bytes": artifact.size_bytes,
        "created_at": artifact.created_at.isoformat(),
    }


def file_meta(uploaded: UploadedFile) -> dict[str, Any]:
    return {
        "id": str(uploaded.id),
        "filename": uploaded.filename,
        "content_type": uploaded.content_type,
        "size_bytes": uploaded.size_bytes,
        "persist": uploaded.persist,
        "created_at": uploaded.created_at.isoformat(),
    }


def task_out(task: Task, artifacts: list[Artifact] | None = None) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "conversation_id": str(task.conversation_id),
        "title": task.title,
        "intent": task.intent,
        "status": task.status.value,
        "surface": task.surface.value,
        "input": {
            "message": task.input.get("message"),
            "file_ids": task.input.get("file_ids") or [],
        },
        "result": task.result,
        "error": task.error,
        "cost_usd": float(task.cost_usd),
        "token_in": task.token_in,
        "token_out": task.token_out,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "ended_at": task.ended_at.isoformat() if task.ended_at else None,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "steps": [step_out(s) for s in task.steps],
        "artifacts": [artifact_meta(a) for a in (artifacts or [])],
    }
