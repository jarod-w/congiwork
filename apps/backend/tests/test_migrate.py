"""迁移文件发现。不需要 Postgres。"""

from __future__ import annotations

from cogniwork.migrate import default_migrations_path, list_migration_files


def test_migration_files_are_numbered_in_order():
    files = list_migration_files(default_migrations_path())
    versions = [version for version, _name, _path in files]
    assert versions == ["0001", "0002", "0003", "0004", "0005", "0006"]
    names = [name for _version, name, _path in files]
    assert names == ["consent", "account", "task", "memory", "profile", "tools"]
