"""Resource governance + user-facing error classes (P0-03 §8 / §9 / M7)."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any
from uuid import UUID

from cogniwork.core.clock import today
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

# 日额度打满后转 economy 路由时给用户的话（P0-03 §8：「并提示用户」）。
# 不说这一句，用户只会觉得「今天它变笨了」—— 那正是降级而非硬停想避免的体验。
DOWNGRADE_NOTICE = (
    "You have reached today's model budget, so I am using the faster, "
    "cheaper model for the rest of today. Quality may drop on complex steps. "
    "It resets at 00:00 UTC.\n"
)

# 每 1k token 的美元费率，按 (vendor, model) 记，输入输出分开。
# 全部是**估值**，`daily_llm_usage` 攒的数据就是用来校准它的（§8）。
# 单一费率的问题不在于不准，而在于「模型 A 比模型 B 贵多少」这件事被抹平了 ——
# 那样定价验证的数据说明不了任何路由决策。
TOKEN_RATES: dict[tuple[str, str], tuple[float, float]] = {
    ("anthropic", "claude-sonnet-4-20250514"): (0.003, 0.015),
    ("openai", "gpt-4.1"): (0.002, 0.008),
    ("openai", "gpt-4.1-mini"): (0.0004, 0.0016),
    ("stub", "stub-local"): (0.0, 0.0),
}

# 认不出的模型（含用户自定义 provider）按内置里最贵的一档估。
# 宁可高估：低估会让任务在成本闸门前多走几步，而那道闸门是防跑飞的。
FALLBACK_RATE = (0.003, 0.015)


def classify_error(code: str) -> dict[str, Any]:
    retryable = code not in {"invalid_input"}
    return {
        "code": code if code in ERROR_COPY else "internal_error",
        "message": ERROR_COPY.get(code, ERROR_COPY["internal_error"]),
        "retryable": retryable,
    }


def rate_for(vendor: str | None, model: str | None) -> tuple[float, float]:
    return TOKEN_RATES.get((str(vendor or ""), str(model or "")), FALLBACK_RATE)


def cost_for_tokens(
    token_in: int,
    token_out: int,
    *,
    vendor: str | None = None,
    model: str | None = None,
) -> float:
    rate_in, rate_out = rate_for(vendor, model)
    return round((token_in / 1000.0) * rate_in + (token_out / 1000.0) * rate_out, 6)


def should_pause_for_cost(task: Any, settings: Settings) -> bool:
    return float(task.cost_usd or 0) >= float(settings.task_cost_usd_limit)


def daily_over_cap(store: Any, user_id: UUID, settings: Settings) -> bool:
    usage = store.get_usage(user_id, today().isoformat())
    return float(usage.get("cost_usd") or 0) >= float(settings.daily_cost_usd_limit)


def record_usage(store: Any, user_id: UUID, cost_usd: float, token_in: int, token_out: int) -> None:
    store.add_usage(user_id, today().isoformat(), cost_usd, token_in, token_out)


class GlobalLlmConcurrency:
    """全局在飞 LLM 调用上限（P0-03 §8 末行）。

    per-(user, provider) 的令牌桶管的是「一个用户别把某个供应商打爆」，管不了
    「一百个用户同时各开三个任务」。供应商的账号级限流是全局的，所以我们的闸门
    也得有一个全局的。

    满了就排队，不失败 —— 与 §6 的限流同一个取舍：让步骤慢一点，别让任务死掉。
    """

    def __init__(self, limit: int, *, wait_timeout_s: float = 120.0) -> None:
        self._limit = max(1, int(limit))
        self._semaphore = threading.BoundedSemaphore(self._limit)
        self._wait_timeout_s = wait_timeout_s

    def __enter__(self) -> GlobalLlmConcurrency:
        started = time.monotonic()
        acquired = self._semaphore.acquire(timeout=self._wait_timeout_s)
        if not acquired:
            # 等不到就当成一次上游失败，由 §9 的错误分类给用户话术。
            from cogniwork.core.errors import RateLimited

            raise RateLimited("The model queue is busy right now. Try that step again shortly.")
        waited = time.monotonic() - started
        if waited > 1.0:
            # 排队本身不是错误，但持续排队说明该调这个上限了 —— 只有失败日志的话
            # 运维看到的是「偶尔限流」，看不到「一直在饱和」。
            logging.getLogger("cogniwork.runtime").info(
                "global llm gate: waited %.1fs for a slot (limit=%s)", waited, self._limit
            )
        return self

    def __exit__(self, *exc: Any) -> None:
        self._semaphore.release()


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
