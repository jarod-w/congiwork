"""运维任务：`execution_audit` 的分区创建与到期回收（P0-07 §7）。

`0001_consent.sql` 里那句「分区的创建与回收由运维任务负责」指的就是这里。
在这个模块存在之前，那个运维任务不存在 —— 于是「保留 12 个月，到期 drop 分区」
只是一句写在文档里的话：审计全落进 DEFAULT 分区，而 DEFAULT 永远 drop 不掉。

两件事，故意分开：

- `ensure_partitions` 是安全的，应用启动时就跑（`main._wire_runtime`）。
- `drop_expired_partitions` 会删数据，只由 cron / 手工触发：
  `python -m cogniwork.maintenance audit-retention`（见 docs/deploy.md）。

DEFAULT 分区保留为安全网。分区没建全时插入不至于失败，代价是落进 DEFAULT 的行
drop 不掉 —— 所以回收时对 DEFAULT 里的过期行用 DELETE。这是 DEFAULT 存在的代价，
不是漏掉的一步。
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, date, datetime
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from .core.clock import now
from .core.config import get_settings

PARENT = "execution_audit"
DEFAULT_PARTITION = f"{PARENT}_default"
RETENTION_MONTHS = 12
PARTITION_RE = re.compile(rf"^{PARENT}_(\d{{4}})_(\d{{2}})$")


def month_start(anchor: date) -> datetime:
    return datetime(anchor.year, anchor.month, 1, tzinfo=UTC)


def next_month(anchor: date) -> date:
    return date(anchor.year + (anchor.month // 12), (anchor.month % 12) + 1, 1)


def partition_name(anchor: date) -> str:
    return f"{PARENT}_{anchor.year:04d}_{anchor.month:02d}"


def parse_partition_month(name: str) -> date | None:
    found = PARTITION_RE.match(name)
    if found is None:
        return None
    return date(int(found.group(1)), int(found.group(2)), 1)


def retention_cutoff(anchor: date, keep_months: int = RETENTION_MONTHS) -> date:
    """保留期起点：这个月之前的分区可以回收。"""
    total = anchor.year * 12 + (anchor.month - 1) - keep_months
    return date(total // 12, total % 12 + 1, 1)


def expired_partitions(names: list[str], cutoff: date) -> list[str]:
    """纯函数，好测。DEFAULT 不在返回值里 —— 它 drop 不掉。"""
    out = []
    for name in names:
        month = parse_partition_month(name)
        if month is not None and month < cutoff:
            out.append(name)
    return sorted(out)


def _existing_partitions(conn: Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT child.relname AS name
        FROM pg_inherits
        JOIN pg_class parent ON parent.oid = pg_inherits.inhparent
        JOIN pg_class child ON child.oid = pg_inherits.inhrelid
        WHERE parent.relname = %s
        """,
        (PARENT,),
    ).fetchall()
    return [row["name"] for row in rows]


def ensure_partitions(conn: Connection, *, anchor: date | None = None, months_ahead: int = 3):
    """建出当月与未来 months_ahead 个月的分区。已存在的跳过。"""
    start = (anchor or now().date()).replace(day=1)
    existing = set(_existing_partitions(conn))
    created: list[str] = []
    month = start
    for _ in range(months_ahead + 1):
        name = partition_name(month)
        if name not in existing:
            lower = month_start(month)
            upper = month_start(next_month(month))
            with conn.transaction():
                if DEFAULT_PARTITION in existing and _default_holds_rows(conn, lower, upper):
                    _adopt_from_default(conn, name, lower, upper)
                else:
                    # 常规路径。一条语句，索引由 PostgreSQL 自动建。
                    conn.execute(
                        f'CREATE TABLE "{name}" PARTITION OF {PARENT} FOR VALUES FROM (%s) TO (%s)',
                        (lower, upper),
                    )
            created.append(name)
        month = next_month(month)
    return created


def _default_holds_rows(conn: Connection, lower: datetime, upper: datetime) -> bool:
    row = conn.execute(
        f"SELECT EXISTS (SELECT 1 FROM {DEFAULT_PARTITION} "
        "WHERE created_at >= %s AND created_at < %s) AS found",
        (lower, upper),
    ).fetchone()
    return bool(row and row["found"])


def _adopt_from_default(conn: Connection, name: str, lower: datetime, upper: datetime) -> None:
    """DEFAULT 里已有这个区间的行时，先把行挪走再 ATTACH。

    直接 `CREATE TABLE ... PARTITION OF` 会被拒绝：新分区的范围与 DEFAULT 里
    已有的行冲突。`INCLUDING INDEXES` 让 ATTACH 复用等价索引，
    不在大表上重建一遍。
    """
    conn.execute(
        f'CREATE TABLE "{name}" (LIKE {PARENT} '
        "INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES)"
    )
    conn.execute(
        f'INSERT INTO "{name}" SELECT * FROM {DEFAULT_PARTITION} '
        "WHERE created_at >= %s AND created_at < %s",
        (lower, upper),
    )
    conn.execute(
        f"DELETE FROM {DEFAULT_PARTITION} WHERE created_at >= %s AND created_at < %s",
        (lower, upper),
    )
    conn.execute(
        f'ALTER TABLE {PARENT} ATTACH PARTITION "{name}" FOR VALUES FROM (%s) TO (%s)',
        (lower, upper),
    )


def drop_expired_partitions(
    conn: Connection,
    *,
    anchor: date | None = None,
    keep_months: int = RETENTION_MONTHS,
) -> dict[str, Any]:
    """回收保留期外的审计数据（P0-07 §7：12 个月）。"""
    cutoff = retention_cutoff((anchor or now().date()).replace(day=1), keep_months)
    names = _existing_partitions(conn)
    dropped = expired_partitions(names, cutoff)
    for name in dropped:
        with conn.transaction():
            conn.execute(f'DROP TABLE "{name}"')
    purged = 0
    if DEFAULT_PARTITION in names:
        with conn.transaction():
            cur = conn.execute(
                f"DELETE FROM {DEFAULT_PARTITION} WHERE created_at < %s",
                (month_start(cutoff),),
            )
            purged = cur.rowcount or 0
    return {"cutoff": cutoff.isoformat(), "dropped": dropped, "purged_from_default": purged}


def audit_retention(
    database_url: str | None = None,
    *,
    keep_months: int = RETENTION_MONTHS,
    months_ahead: int = 3,
) -> dict[str, Any]:
    url = database_url or get_settings().database_url
    with Connection.connect(url, row_factory=dict_row) as conn:
        created = ensure_partitions(conn, months_ahead=months_ahead)
        recycled = drop_expired_partitions(conn, keep_months=keep_months)
    return {"created": created, **recycled}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CogniWork maintenance tasks")
    sub = parser.add_subparsers(dest="task", required=True)
    audit = sub.add_parser(
        "audit-retention",
        help="Create upcoming execution_audit partitions and drop expired ones",
    )
    audit.add_argument("--database-url", default=None)
    audit.add_argument("--keep-months", type=int, default=RETENTION_MONTHS)
    audit.add_argument("--months-ahead", type=int, default=3)
    args = parser.parse_args(argv)
    if args.task == "audit-retention":
        outcome = audit_retention(
            args.database_url,
            keep_months=args.keep_months,
            months_ahead=args.months_ahead,
        )
        print(
            f"cutoff={outcome['cutoff']} created={outcome['created']} "
            f"dropped={outcome['dropped']} purged_from_default={outcome['purged_from_default']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
