"""CI 守护：前后端共享契约的一致性。

`packages/shared-types` 与后端各有一份错误码、事件名、审批动作的定义。
两份定义是**同一个契约的两种语言表述**，不是两个独立的东西 ——
只改一边不会有任何编译错误或运行时报错，前端会安静地收到一个它不认识的
错误码，然后走进 default 分支。这组测试是那次不一致的唯一拦截点。
"""

from __future__ import annotations

import re
from pathlib import Path

from cogniwork.core.errors import ErrorCode

SHARED_TYPES = Path(__file__).resolve().parents[4] / "packages" / "shared-types" / "src"


def _string_array(source: str, const_name: str) -> set[str]:
    """从 `export const NAME = [...] as const;` 里抽出字符串字面量。"""
    match = re.search(rf"export const {const_name}\s*=\s*\[(.*?)\]\s*as const", source, re.DOTALL)
    assert match, f"在 shared-types 里找不到 {const_name}"
    return set(re.findall(r"'([^']+)'", match.group(1)))


def test_error_codes_match_between_python_and_typescript():
    """00-conventions.md §6 的受控错误码词表，两边必须一致。"""
    ts = _string_array((SHARED_TYPES / "errors.ts").read_text(encoding="utf-8"), "ERROR_CODES")
    py = {code.value for code in ErrorCode}
    assert ts == py, (
        "错误码词表不一致：\n"
        f"  只在 TypeScript: {sorted(ts - py)}\n"
        f"  只在 Python:     {sorted(py - ts)}\n"
        "两处定义的是同一份受控词表（00-conventions.md §6），改一边必须改另一边。"
    )


def test_risk_values_match_registry_vocabulary(registry):
    """shared-types 的 Risk 联合类型必须覆盖 scopes.yaml 的 risk 词表。"""
    source = (SHARED_TYPES / "consent.ts").read_text(encoding="utf-8")
    match = re.search(r"export type Risk\s*=\s*([^;]+);", source)
    assert match, "shared-types 里找不到 Risk 类型"
    ts_values = set(re.findall(r"'([^']+)'", match.group(1)))
    assert ts_values == set(registry.vocabularies["risk"]), (
        f"Risk 词表不一致: TS={sorted(ts_values)} vs "
        f"scopes.yaml={sorted(registry.vocabularies['risk'])}"
    )


def test_shared_types_does_not_hardcode_scope_keys():
    """前端不得复制一份 Scope 列表。

    单一事实来源是 config/scopes.yaml，前端从 GET /api/v1/scopes 拉。
    在 shared-types 里写死 Scope key，就等于有了第二个事实来源 ——
    加一个 Scope 时没人会记得去改前端那份，于是设置页少一项。
    """
    offenders: list[str] = []
    scope_like = re.compile(r"'(tool|desktop|browser|file|telemetry|memory|llm):[a-z_*]+:[a-z_]+'")
    for path in SHARED_TYPES.glob("*.ts"):
        for match in scope_like.finditer(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.name}: {match.group(0)}")
    assert not offenders, (
        "shared-types 里出现了硬编码的 Scope key:\n  "
        + "\n  ".join(offenders)
        + "\n\nScope 列表从 API 拉取，不要在前端复制一份。"
    )
