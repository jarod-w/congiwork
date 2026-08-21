"""Resource governance + finalize honesty (P0-03 M7)."""

from __future__ import annotations

from types import SimpleNamespace

from cogniwork.core.config import Settings
from cogniwork.runtime.governance import (
    classify_error,
    cost_for_tokens,
    finalize_result,
    should_pause_for_cost,
)


def test_cost_pause_threshold():
    settings = Settings(task_cost_usd_limit=0.5)
    task = SimpleNamespace(cost_usd=0.51)
    assert should_pause_for_cost(task, settings) is True
    task.cost_usd = 0.1
    assert should_pause_for_cost(task, settings) is False


def test_finalize_lists_unfinished_steps():
    steps = [
        SimpleNamespace(title="Read the file", status=SimpleNamespace(value="succeeded")),
        SimpleNamespace(title="Send the note", status=SimpleNamespace(value="failed")),
        SimpleNamespace(title="Unused", status=SimpleNamespace(value="skipped")),
    ]
    task = SimpleNamespace(steps=steps)
    result = finalize_result(task, "Partial work", [])
    assert result["partial"] is True
    assert "Send the note" in result["failed_steps"]
    assert "Unused" in result["skipped_steps"]
    assert "Read the file" in result["completed_steps"]


def test_error_classes_are_readable():
    item = classify_error("permission_denied")
    assert "enable" in item["message"].lower() or "paste" in item["message"].lower()
    assert classify_error("invalid_input")["retryable"] is False
    assert cost_for_tokens(1000, 0) > 0


def test_cost_rates_differ_per_model():
    """单一费率会把「哪个模型贵」从 daily_llm_usage 里抹掉（P0-03 §8）。"""
    from cogniwork.runtime.governance import rate_for

    premium = cost_for_tokens(1000, 1000, vendor="anthropic", model="claude-sonnet-4-20250514")
    cheap = cost_for_tokens(1000, 1000, vendor="openai", model="gpt-4.1-mini")
    assert premium > cheap
    # 输入输出分开计价：同样的 token 总数，输出多的更贵。
    assert cost_for_tokens(0, 2000, vendor="openai", model="gpt-4.1") > cost_for_tokens(
        2000, 0, vendor="openai", model="gpt-4.1"
    )
    # 认不出的模型（含用户自定义 provider）按最贵一档估，宁可高估。
    assert rate_for("someone-else", "their-model") == rate_for(
        "anthropic", "claude-sonnet-4-20250514"
    )


def test_daily_cap_uses_utc_not_the_server_timezone():
    """日额度的日界必须与 daily_llm_usage 的记账日界一致（UTC）。"""
    from datetime import UTC, datetime, timedelta

    from cogniwork.core.clock import today
    from cogniwork.runtime.governance import daily_over_cap, record_usage

    assert today() == datetime.now(UTC).date()

    class _Store:
        def __init__(self) -> None:
            self.rows: dict[str, float] = {}

        def add_usage(self, user_id, day, cost_usd, token_in, token_out):
            self.rows[day] = self.rows.get(day, 0.0) + cost_usd

        def get_usage(self, user_id, day):
            return {"cost_usd": self.rows.get(day, 0.0)}

    store = _Store()
    record_usage(store, "u1", 6.0, 10, 10)
    assert list(store.rows) == [today().isoformat()]
    assert daily_over_cap(store, "u1", Settings(daily_cost_usd_limit=5.0)) is True
    # 昨天（UTC）的用量不该算进今天
    store.rows = {(today() - timedelta(days=1)).isoformat(): 99.0}
    assert daily_over_cap(store, "u1", Settings(daily_cost_usd_limit=5.0)) is False


def test_global_llm_concurrency_blocks_past_the_limit():
    """per-(user, provider) 桶管不到跨用户总量（P0-03 §8 末行）。"""
    import threading

    from cogniwork.core.errors import RateLimited
    from cogniwork.runtime.governance import GlobalLlmConcurrency

    gate = GlobalLlmConcurrency(1, wait_timeout_s=0.05)
    held = threading.Event()
    release = threading.Event()

    def _hold():
        with gate:
            held.set()
            release.wait(2)

    worker = threading.Thread(target=_hold, daemon=True)
    worker.start()
    assert held.wait(2)
    try:
        with gate:
            raise AssertionError("the global gate let a second call through")
    except RateLimited:
        pass
    finally:
        release.set()
        worker.join(2)
