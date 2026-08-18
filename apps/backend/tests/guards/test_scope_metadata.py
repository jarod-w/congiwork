"""CI 守护：Scope 元数据完整性（P0-07 §8.2）。

这一组测试的作用是**替评审人记住规则**。00-conventions.md §5 那张检查表
靠人逐项勾选，人会累、会赶进度、会觉得「这次特殊」。这些断言不会。

失败即阻塞合并。
"""

from __future__ import annotations

import pytest

from cogniwork.consent.models import Risk, TrustLevel
from cogniwork.consent.registry import (
    INDUCEMENT_PATTERNS,
    KEY_PATTERN,
    PLACEHOLDER_PATTERN,
    UNAVAILABLE_PATTERN,
)

DELIVERY_LOCALE = "en-US"  # A8：交付基线


def test_registry_is_not_empty(registry):
    assert len(registry) > 0, "Scope 注册表为空 —— 加载路径或文件内容有问题"


def test_every_key_matches_naming_convention(registry):
    """<domain>:<target>:<capability>（00-conventions.md §3）。"""
    for spec in registry:
        assert KEY_PATTERN.match(spec.key), f"{spec.key} 不符合 Scope 命名规范"


def test_domain_and_capability_in_vocabulary(registry):
    for spec in registry:
        assert spec.domain in registry.vocabularies["domain"], f"{spec.key}: domain 越界"
        assert spec.capability in registry.vocabularies["capability"], (
            f"{spec.key}: capability 越界"
        )


def test_six_metadata_fields_present_in_delivery_locale(registry):
    """六项元数据齐全（硬约束 2）。

    六项 = risk + trust_level + display_name + collects + retention + degraded_behavior。
    前两项是结构化的，后四项是面向用户的自然语言。
    """
    for spec in registry:
        assert isinstance(spec.risk, Risk)
        assert isinstance(spec.trust_level, TrustLevel)
        assert DELIVERY_LOCALE in spec.copy, (
            f"{spec.key}: 缺交付语言 {DELIVERY_LOCALE} 的文案（A8 交付基线）"
        )
        copy = spec.copy[DELIVERY_LOCALE]
        for field in ("display_name", "collects", "retention", "degraded_behavior"):
            assert getattr(copy, field).strip(), f"{spec.key}: {field} 为空"


def test_degraded_behavior_is_not_a_placeholder(registry):
    for spec in registry:
        for locale, copy in spec.copy.items():
            assert not PLACEHOLDER_PATTERN.match(copy.degraded_behavior), (
                f"{spec.key}[{locale}]: degraded_behavior 是占位符"
            )


def test_degraded_behavior_never_says_unavailable(registry):
    """硬约束 6：degraded_behavior 不得是「功能不可用」。

    这条是整个自愿模型的地基。如果一个 Scope 不开启就没法用，
    那它就不是可选的，「自愿授权」只是说法。
    """
    for spec in registry:
        for locale, copy in spec.copy.items():
            assert not UNAVAILABLE_PATTERN.search(copy.degraded_behavior), (
                f"{spec.key}[{locale}]: degraded_behavior 表达了功能不可用 —— "
                f"{copy.degraded_behavior!r}"
            )


def test_no_inducement_language(registry):
    """授权文案不得诱导（00-conventions.md §5）。

    「开启后才能获得完整体验」这类表述会把「自愿」变成「不开启是你的损失」，
    这正是 P0-07 §10 边界第 1 条所依赖的前提被侵蚀的方式。
    """
    for spec in registry:
        for locale, copy in spec.copy.items():
            for field in ("display_name", "collects", "retention", "degraded_behavior"):
                text = getattr(copy, field)
                for pattern in INDUCEMENT_PATTERNS:
                    assert not pattern.search(text), (
                        f"{spec.key}[{locale}].{field} 含诱导性表述 {pattern.pattern!r}"
                    )


def test_irreversible_scopes_are_l3(registry):
    """irreversible 必然是 L3 —— 不可撤销的动作不可能属于只读层。"""
    for spec in registry.by_risk(Risk.IRREVERSIBLE):
        assert spec.trust_level is TrustLevel.L3, (
            f"{spec.key}: risk=irreversible 但 trust_level={spec.trust_level}"
        )


def test_l2_scopes_are_read_only(registry):
    """L2 是「只读工具」层（00-conventions.md §3.1），不能混进写能力。"""
    for spec in registry:
        if spec.trust_level is TrustLevel.L2 and spec.domain == "tool":
            assert spec.risk is Risk.READ, (
                f"{spec.key}: L2 工具的 risk 必须是 read，实际 {spec.risk}"
            )


def test_read_and_write_are_separate_scopes(registry):
    """硬约束：授权 A 不等于授权 B（00-conventions.md §3 规则 2）。

    对每个有写能力的 target，必须存在独立的读 Scope —— 连接一个工具「只读」
    绝不能隐含写入或发送能力（P0-05 §1 G2）。
    """
    by_target: dict[tuple[str, str], set[str]] = {}
    for spec in registry:
        by_target.setdefault((spec.domain, spec.target), set()).add(spec.capability)

    for (domain, target), caps in by_target.items():
        if domain != "tool":
            continue
        if caps & {"write", "send"}:
            assert "read" in caps, (
                f"{domain}:{target}: 有写/发送能力却没有独立的 read Scope —— "
                "读写必须分离，否则「只读连接」在实现上无法表达"
            )


def test_unlaunched_connectors_are_not_registered(registry):
    """注册表只登记已上线/即将上线的能力（P0-05 §4.2）。

    注册表是运行时读取的：出现一个没有实现的 Scope，等于在设置页给用户
    展示一个点不开的授权项。Slack 已按 P0-05 §2.1 移出 Phase 1 首批。
    """
    launched_tool_targets = {"gmail", "gcal", "notion", "github"}
    for spec in registry:
        if spec.domain == "tool":
            assert spec.target in launched_tool_targets, (
                f"{spec.key}: {spec.target!r} 不在 Phase 1 首批连接器内。"
                "若要新增连接器，先改 P0-05 §2.1 并登记设计偏离。"
            )


@pytest.mark.release
def test_delivery_copy_passed_native_review(registry):
    """发版检查项（A8 落实要求 ②、P0-07 §13 验收 3）。

    授权说明文案必须过英文母语审校。这个断言**不阻塞 PR 合并**
    （标了 release marker），只在发版前跑 —— 因为开发过程中新增 Scope
    时文案必然是待审状态，那时挡住合并没有意义。

    跑法：pytest -m release
    """
    pending = [s.key for s in registry if s.review_status != "approved"]
    assert not pending, (
        "以下 Scope 的交付文案尚未通过英文母语审校，不可发版:\n  "
        + "\n  ".join(pending)
        + "\n\n审校通过后把 config/scopes.yaml 里对应条目的 review_status 改为 approved。"
    )
