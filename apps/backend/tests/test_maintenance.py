"""审计分区的创建与回收（P0-07 §7、§14 M3）。

纯函数部分不需要 Postgres；真正建 / drop 分区的部分需要，本地无基础设施时 skip。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from cogniwork.core.clock import now
from cogniwork.core.config import get_settings
from cogniwork.core.ids import new_id
from cogniwork.maintenance import (
    DEFAULT_PARTITION,
    drop_expired_partitions,
    ensure_partitions,
    expired_partitions,
    next_month,
    parse_partition_month,
    partition_name,
    retention_cutoff,
)


def test_month_arithmetic_wraps_at_december():
    assert next_month(date(2026, 12, 1)) == date(2027, 1, 1)
    assert partition_name(date(2026, 1, 1)) == "execution_audit_2026_01"
    assert parse_partition_month("execution_audit_2026_01") == date(2026, 1, 1)
    assert parse_partition_month("execution_audit_default") is None


def test_retention_keeps_twelve_months():
    cutoff = retention_cutoff(date(2026, 8, 1))
    assert cutoff == date(2025, 8, 1)
    names = [
        "execution_audit_2025_07",
        "execution_audit_2025_08",
        "execution_audit_2026_08",
        DEFAULT_PARTITION,
    ]
    # 12 个月内的留着；DEFAULT 不在可 drop 列表里 —— 它 drop 不掉。
    assert expired_partitions(names, cutoff) == ["execution_audit_2025_07"]


def test_default_partition_is_never_reported_as_droppable():
    """这一条正是 §7 之前落不了地的原因，值得单独钉住。"""
    assert expired_partitions([DEFAULT_PARTITION], date(2030, 1, 1)) == []


pg = pytest.mark.skipif(
    get_settings().store_backend != "postgres",
    reason="COGNIWORK_STORE_BACKEND is not postgres",
)


@pg
def test_partitions_are_created_and_expired_ones_dropped():
    from cogniwork.core.db import open_pool
    from cogniwork.migrate import apply_migrations

    apply_migrations()
    pool = open_pool(get_settings())
    try:
        with pool.connection() as conn:
            ensure_partitions(conn, months_ahead=2)
            names = _partition_names(conn)
            assert partition_name(now().date()) in names

            # 造一条过期审计：落进 DEFAULT，回收时应被 DELETE 清掉。
            old = now() - timedelta(days=800)
            conn.execute(
                """
                INSERT INTO execution_audit
                    (id, user_id, surface, action, result, created_at)
                VALUES (%s, %s, 'web', 'test.retention', 'allowed', %s)
                """,
                (new_id(), new_id(), old),
            )
            outcome = drop_expired_partitions(conn)
            assert outcome["purged_from_default"] >= 1
            left = conn.execute(
                "SELECT count(*) AS n FROM execution_audit WHERE created_at < %s",
                (now() - timedelta(days=400),),
            ).fetchone()
            assert int(left["n"]) == 0
    finally:
        pool.close()


def _partition_names(conn) -> list[str]:
    rows = conn.execute(
        """
        SELECT child.relname AS name
        FROM pg_inherits
        JOIN pg_class parent ON parent.oid = pg_inherits.inhparent
        JOIN pg_class child ON child.oid = pg_inherits.inhrelid
        WHERE parent.relname = 'execution_audit'
        """
    ).fetchall()
    return [row["name"] for row in rows]
