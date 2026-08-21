"""迁移文件发现。不需要 Postgres。"""

from __future__ import annotations

from cogniwork.migrate import default_migrations_path, list_migration_files


def test_migration_files_are_numbered_without_gaps():
    """编号必须连续且不重复 —— migrate 按前缀顺序执行，缺号意味着有文件没进来，
    重号意味着两份迁移的先后没有定义。断言的是这条性质，不是当前的文件清单，
    这样加一份迁移不用回来改测试。
    """
    files = list_migration_files(default_migrations_path())
    versions = [version for version, _name, _path in files]
    assert versions == [f"{i:04d}" for i in range(1, len(versions) + 1)], versions


def test_first_migrations_are_the_expected_foundation():
    """地基几份的顺序有依赖关系（task 引用 conversation，runtime_state 引用 task），
    所以这几个前缀固定下来。
    """
    files = list_migration_files(default_migrations_path())
    names = [name for _version, name, _path in files]
    assert names[:4] == ["consent", "account", "task", "memory"]
    assert "runtime_state" in names
    assert names.index("runtime_state") > names.index("task")
