"""时间。

约定（00-conventions.md §2）：所有时间字段 timestamptz，统一存 UTC，字段名 *_at。
不要用 datetime.now()（本地时区）或 utcnow()（naive）。
"""

from __future__ import annotations

from datetime import UTC, datetime


def now() -> datetime:
    """当前 UTC 时间，带时区信息。"""
    return datetime.now(UTC)
