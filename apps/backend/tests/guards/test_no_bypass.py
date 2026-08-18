"""CI 守护：权限检查无旁路（P0-07 §8.2）。

硬约束 3：检查点唯一地在 Agent Runtime 的工具调用链上，
**各 Executor 内部不做也不能做权限判断。**

这一组是**静态检查** —— 它扫源码，不需要 Executor 已经存在。
这正是把它放在第一周写的理由：等 Executor 写完再加这条，
那时权限判断已经渗进各处，检查一开就是全面飘红。

P0-07 §8.2 还要求一条动态检查（mock ConsentService 返回 DENY，
断言无任何上游调用发生）。那条需要真的有 Executor 才能写，
留在 P0-03 M3 落地时补 —— 见文件末尾的占位。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "cogniwork"

# 允许出现授权判断逻辑的模块 —— 唯一检查点及其直接支撑。
# store 与授权/撤销 API 是检查点的写入面，不是第二条判定路径：
# 它们只 append 记录，不得调用 ConsentService.check，也不得出现 check() 定义。
CONSENT_OWNED = {
    "consent/service.py",
    "consent/registry.py",
    "consent/models.py",
    "consent/store.py",
    "api/v1/consent.py",
}

# 判定「这里在做权限判断」的信号
CONSENT_SYMBOLS = {"ConsentDecision", "ConsentService", "always_allow", "is_granted"}


def _python_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def _rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix()


def test_consent_symbols_only_appear_in_the_checkpoint():
    """除唯一检查点外，任何模块不得引用授权判定符号。

    这条会在第一个 Executor 里写 `if decision is ConsentDecision.ALLOW` 时立刻失败。
    那正是它存在的意义 —— Executor 拿到的应该是「已经批准的调用」，
    不是「一个待判断的请求」。
    """
    offenders: list[str] = []
    for path in _python_files():
        rel = _rel(path)
        if rel in CONSENT_OWNED:
            continue
        source = path.read_text(encoding="utf-8")
        hits = sorted(sym for sym in CONSENT_SYMBOLS if sym in source)
        if hits:
            offenders.append(f"{rel}: {', '.join(hits)}")

    assert not offenders, (
        "以下模块出现了授权判断符号，违反硬约束 3（权限检查点唯一）:\n  "
        + "\n  ".join(offenders)
        + "\n\nExecutor 应当接收「已批准的调用」，而不是自己判断能不能调用。"
        "\n若确实是新的检查点支撑模块，把它加进本文件的 CONSENT_OWNED 并在 PR 里说明理由。"
    )


def test_consent_service_check_has_a_single_definition():
    """`check` 只能有一个实现。存在第二个就意味着有第二条判定路径。"""
    definitions: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "check":
                definitions.append(f"{_rel(path)}:{node.lineno}")

    assert len(definitions) == 1, f"check() 有多处定义，检查点不唯一: {definitions}"
    assert definitions[0].startswith("consent/service.py:"), (
        f"check() 不在 consent/service.py 里: {definitions[0]}"
    )


def test_consent_write_api_does_not_judge_permission():
    """授权/撤销 API 只负责落记录，不能变成第二条判定路径。"""
    source = (SRC / "api" / "v1" / "consent.py").read_text(encoding="utf-8")
    assert "ConsentService" not in source
    assert "ConsentDecision" not in source


def test_no_hardcoded_locale_outside_config():
    """A8 落实要求 ①：语言从配置读取，不硬编码默认值。

    代码里出现字面量 "en-US" / "zh-CN" 就是把语言焊死了。唯一允许的地方是
    core/config.py（配置项的默认值本身）与测试。
    """
    allowed = {"core/config.py"}
    offenders: list[str] = []
    for path in _python_files():
        rel = _rel(path)
        if rel in allowed:
            continue
        source = path.read_text(encoding="utf-8")
        for literal in ('"en-US"', "'en-US'", '"zh-CN"', "'zh-CN'"):
            if literal in source:
                offenders.append(f"{rel}: {literal}")

    assert not offenders, (
        "以下位置硬编码了语言，违反 A8 落实要求 ①:\n  "
        + "\n  ".join(offenders)
        + "\n\n语言从 core.config.get_settings() 读取。"
    )


def test_no_uuid4_for_primary_keys():
    """00-conventions.md §2：主键统一 UUIDv7，用 core.ids.new_id()。"""
    offenders = [
        _rel(path)
        for path in _python_files()
        if _rel(path) != "core/ids.py" and "uuid4()" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        f"以下模块直接用了 uuid4()，主键应统一 UUIDv7（core.ids.new_id）: {offenders}"
    )


def test_no_naive_utcnow():
    """00-conventions.md §2：时间统一 UTC 且带时区，用 core.clock.now()。"""
    offenders = [
        _rel(path)
        for path in _python_files()
        if _rel(path) != "core/clock.py" and ("utcnow()" in path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        f"以下模块用了 utcnow()（naive datetime），应改用 core.clock.now(): {offenders}"
    )


@pytest.mark.skip(reason="待 P0-03 M3 工具抽象层落地后启用")
def test_executors_make_no_upstream_call_when_denied():
    """动态版本的无旁路检查（P0-07 §8.2）。

    对每个 Executor 的集成测试：mock ConsentService 返回 DENY，
    断言无任何上游调用发生。

    现在还没有 Executor，所以是 skip 而不是删掉 —— 留在这里是为了
    让 P0-03 M3 的实现者看到这条测试在等他，而不是等他想起来要写。
    """
