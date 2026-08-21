"""时间。

约定（00-conventions.md §2）：所有时间字段 timestamptz，统一存 UTC，字段名 *_at。
不要用 datetime.now()（本地时区）或 utcnow()（naive）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime


def now() -> datetime:
    """当前 UTC 时间，带时区信息。"""
    return datetime.now(UTC)


def today() -> date:
    """当前 UTC 日期。

    `date.today()` 走本地时区，日额度会在服务器本地午夜翻页 —— 那个时刻既不是
    用户的午夜，也不是我们记录里任何一个时间戳的午夜（`P0-03` §8 的日额度和
    `daily_llm_usage` 都按 UTC 记）。同一个额度用两套日界会对不上账。
    """
    return now().date()
