"""Resource governance + user-facing error classes (P0-03 §8 / §9 / M7)."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from cogniwork.core.config import Settings

ERROR_COPY = {
    "permission_denied": (
        "I need you to enable this before I can finish the step. "
        "You can also paste the content instead."
    ),
    "upstream_error": "The connected service did not respond.",
    "tool_failed": "That step did not complete.",
    "invalid_input": "I cannot use this input as it is.",
    "budget_exceeded": "This task is costing more than expected. Continue?",
    "internal_error": "Something went wrong. The error was recorded.",
}


def classify_error(code: str) -> dict[str, Any]:
    retryable = code not in {"invalid_input"}
    return {
        "code": code if code in ERROR_COPY else "internal_error",
        "message": ERROR_COPY.get(code, ERROR_COPY["internal_error"]),
        "retryable": retryable,
    }


def cost_for_tokens(token_in: int, token_out: int, *, usd_per_1k: float = 0.003) -> float:
    return round(((token_in + token_out) / 1000.0) * usd_per_1k, 6)


def should_pause_for_cost(task: Any, settings: Settings) -> bool:
    return float(task.cost_usd or 0) >= float(settings.task_cost_usd_limit)


def daily_over_cap(store: Any, user_id: UUID, settings: Settings) -> bool:
    usage = store.get_usage(user_id, date.today().isoformat())
    return float(usage.get("cost_usd") or 0) >= float(settings.daily_cost_usd_limit)


def record_usage(store: Any, user_id: UUID, cost_usd: float, token_in: int, token_out: int) -> None:
    store.add_usage(user_id, date.today().isoformat(), cost_usd, token_in, token_out)


def finalize_result(task: Any, summary: str, artifacts: list[Any]) -> dict[str, Any]:
    def _status(step: Any) -> str:
        return getattr(step.status, "value", step.status)

    completed = [s.title for s in task.steps if _status(s) == "succeeded"]
    skipped = [s.title for s in task.steps if _status(s) in {"skipped", "failed"}]
    failed = [s.title for s in task.steps if _status(s) == "failed"]
    return {
        "summary": summary,
        "artifact_ids": [str(a.id) for a in artifacts],
        "completed_steps": completed,
        "skipped_steps": skipped,
        "failed_steps": failed,
        "partial": bool(failed or skipped),
    }
