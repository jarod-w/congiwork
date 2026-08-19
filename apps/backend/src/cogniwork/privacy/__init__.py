"""隐私中心：导出、物理删除、账号删除（P0-07 §7 / §9 / M5）。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from cogniwork.consent.models import ConsentAction
from cogniwork.core.config import get_settings
from cogniwork.core.hashing import anonymize_user_id
from cogniwork.memory.models import MemoryStatus
from cogniwork.memory.settings import settings_out

_ACTIVITY = {
    "allowed": "completed",
    "denied": "was not allowed",
    "approved": "was approved",
    "rejected": "was rejected",
    "failed": "failed",
}


def privacy_overview(
    *,
    user_id: UUID,
    consent_store: Any,
    memory: Any,
    task_store: Any,
    settings_store: Any,
    registry: Any,
    locale: str,
    fallback: str,
) -> dict[str, Any]:
    grants = []
    for state in consent_store.list_current(str(user_id)):
        spec = registry.get(state.scope_key)
        copy = spec.copy_for(locale, fallback) if spec else None
        grants.append(
            {
                "scope_key": state.scope_key,
                "action": state.action.value,
                "skip_repeat_prompt": state.skip_repeat_prompt,
                "display_name": copy.display_name if copy else state.scope_key,
                "trust_level": spec.trust_level.value if spec else None,
                "risk": spec.risk.value if spec else None,
            }
        )
    files = list_files(task_store, user_id)
    return {
        "authorizations": grants,
        "data": {
            "memories": memory.store.count(user_id),
            "pending_memories": memory.store.count(user_id, status=MemoryStatus.PENDING),
            "tasks": len(task_store.list_tasks(user_id)),
            "files": len(files),
        },
        "settings": settings_out(settings_store.get(user_id)),
        "boundaries": {
            "personal_opt_in_only": True,
            "admin_cannot_enable": True,
            "markets": (
                "This service is offered to English-speaking markets, primarily "
                "the United States. It is not offered in mainland China or the EU."
            ),
        },
    }


def export_user(
    *,
    user_id: UUID,
    email: str,
    memory: Any,
    task_store: Any,
    consent_store: Any,
    audit: Any,
    settings_store: Any,
) -> dict[str, Any]:
    tasks = [
        {
            "id": str(task.id),
            "title": task.title,
            "status": task.status.value,
            "created_at": task.created_at.isoformat(),
            "input": {"message": (task.input or {}).get("message")},
        }
        for task in task_store.list_tasks(user_id)
    ]
    files = [
        {
            "id": str(item.id),
            "filename": item.filename,
            "size_bytes": item.size_bytes,
            "persist": item.persist,
            "created_at": item.created_at.isoformat(),
        }
        for item in list_files(task_store, user_id)
    ]
    grants = [
        {
            "scope_key": state.scope_key,
            "action": state.action.value,
            "skip_repeat_prompt": state.skip_repeat_prompt,
        }
        for state in consent_store.list_current(str(user_id))
        if state.action is ConsentAction.GRANTED
    ]
    return {
        "account": {"id": str(user_id), "email": email},
        "memories": memory.export(user_id),
        "tasks": tasks,
        "files": files,
        "authorizations": grants,
        "audit": list_audit(audit, str(user_id), 500),
        "settings": settings_out(settings_store.get(user_id)),
    }


def list_audit(audit: Any, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    if hasattr(audit, "list_for_user"):
        rows = audit.list_for_user(user_id, limit=limit)
    else:
        rows = [row for row in getattr(audit, "rows", []) if row["user_id"] == user_id][-limit:]
        rows = list(reversed(rows))
    out = []
    for row in rows:
        created = row["created_at"]
        ts = created.isoformat() if hasattr(created, "isoformat") else str(created)
        result = row.get("result") or ""
        out.append(
            {
                "id": row.get("id"),
                "task_id": row.get("task_id"),
                "scope_key": row.get("scope_key"),
                "action": row.get("action"),
                "result": result,
                "created_at": ts,
                "target_digest": row.get("target_digest"),
                "summary": _activity_line(
                    row.get("action") or "", result, row.get("target_digest")
                ),
            }
        )
    return out


def delete_account_data(
    *,
    user_id: UUID,
    memory: Any,
    task_store: Any,
    settings_store: Any,
    approval_store: Any,
    audit: Any,
    consent_store: Any,
    account_store: Any,
) -> dict[str, Any]:
    """除 consent_record 外全部物理删除；consent_record 匿名化保留（B1）。"""
    memories = memory.purge_all(user_id)
    tasks = delete_tasks_for_user(task_store, user_id)
    settings_store.delete(user_id)
    if hasattr(approval_store, "delete_for_user"):
        approval_store.delete_for_user(user_id)
    if hasattr(audit, "delete_for_user"):
        audit.delete_for_user(str(user_id))
    replacement = anonymize_user_id(str(user_id), get_settings().ip_hash_pepper)
    anonymized = consent_store.anonymize_user(str(user_id), replacement)
    if hasattr(account_store, "delete"):
        account_store.delete(user_id)
    return {
        "deleted": {
            "memories": memories,
            "tasks": tasks,
            "account": True,
        },
        "consent_records_anonymized": anonymized,
        "backup_invalidation": {
            "promised_hours": 72,
            "status": "scheduled",
        },
    }


def list_files(task_store: Any, user_id: UUID) -> list[Any]:
    if hasattr(task_store, "list_files"):
        return task_store.list_files(user_id)
    files = getattr(task_store, "files", None)
    if isinstance(files, dict):
        return [item for item in files.values() if item.user_id == user_id]
    return []


def delete_tasks_for_user(task_store: Any, user_id: UUID) -> int:
    if hasattr(task_store, "delete_for_user"):
        return task_store.delete_for_user(user_id)
    tasks = [task.id for task in task_store.list_tasks(user_id)]
    for task_id in tasks:
        task_store.tasks.pop(task_id, None)
    conv_ids = [c.id for c in task_store.list_conversations(user_id)]
    for conv_id in conv_ids:
        task_store.conversations.pop(conv_id, None)
    for file_id in [item.id for item in list_files(task_store, user_id)]:
        task_store.files.pop(file_id, None)
    artifacts = getattr(task_store, "artifacts", {})
    gone = [key for key, item in artifacts.items() if item.user_id == user_id]
    for key in gone:
        artifacts.pop(key, None)
    return len(tasks)


def _activity_line(action: str, result: str, digest: Any) -> str:
    verb = _ACTIVITY.get(result, result)
    extra = ""
    if isinstance(digest, dict) and "to_count" in digest:
        extra = f" ({digest['to_count']} recipients)"
    name = action.replace("_", " ")
    return f"{name} {verb}{extra}".strip()
