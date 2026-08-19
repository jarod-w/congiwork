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
