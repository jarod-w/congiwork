"""SQL 迁移工具。

约定（00-conventions.md §2）的表结构写在 apps/backend/migrations/*.sql。
本模块按文件名的数字前缀顺序执行，并记入 schema_migrations。

不用 Alembic：现有迁移是手写 SQL（物化视图、按月分区），没有 ORM 模型可生成。
接入点是 `python -m cogniwork.migrate`，CI 在跑测试之前执行。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from psycopg import ClientCursor, Connection
from psycopg.rows import dict_row

from .core.clock import now
from .core.config import get_settings

FILE_RE = re.compile(r"^(\d+)_(.+)\.sql$")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     text PRIMARY KEY,
    name        text NOT NULL,
    applied_at  timestamptz NOT NULL
)
"""


def default_migrations_path() -> Path:
    override = os.environ.get("COGNIWORK_MIGRATIONS_PATH")
    if override:
        return Path(override)

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "migrations"
        if candidate.is_dir() and any(candidate.glob("*.sql")):
            return candidate

    return Path.cwd() / "migrations"


def list_migration_files(path: Path) -> list[tuple[str, str, Path]]:
    found: list[tuple[str, str, Path]] = []
    for file in sorted(path.glob("*.sql")):
        match = FILE_RE.match(file.name)
        if match is None:
            continue
        found.append((match.group(1), match.group(2), file))
    return found


def _applied_versions(conn: Connection) -> set[str]:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row["version"] for row in rows}


def apply_migrations(
    database_url: str | None = None,
    migrations_path: Path | None = None,
) -> list[str]:
    """执行尚未应用的迁移。返回本次新应用的 version 列表。"""
    url = database_url or get_settings().database_url
    path = migrations_path or default_migrations_path()
    if not path.is_dir():
        raise FileNotFoundError(f"migrations directory not found: {path}")

    applied: list[str] = []
    # ClientCursor 走 simple query protocol，才能一次执行整份 SQL 文件。
    with Connection.connect(url, row_factory=dict_row, cursor_factory=ClientCursor) as conn:
        conn.execute(_CREATE_TABLE)
        conn.commit()
        done = _applied_versions(conn)
        for version, name, file in list_migration_files(path):
            if version in done:
                continue
            script = file.read_text(encoding="utf-8")
            # 一条迁移里的所有语句与 schema_migrations 写入同一事务：
            # 跑到一半失败必须整份回滚，否则重跑会撞上「表已存在」。
            with conn.transaction():
                conn.execute(script)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (%s, %s, %s)",
                    (version, name, now()),
                )
            applied.append(f"{version}_{name}")
    return applied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply CogniWork SQL migrations")
    parser.add_argument(
        "--database-url",
        default=None,
        help="Postgres URL (default: COGNIWORK_DATABASE_URL)",
    )
    parser.add_argument(
        "--migrations-path",
        default=None,
        type=Path,
        help="Directory of numbered .sql files",
    )
    args = parser.parse_args(argv)
    applied = apply_migrations(args.database_url, args.migrations_path)
    if applied:
        print("applied:", ", ".join(applied))
    else:
        print("already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
