"""CI 守护：ConsentService 的不变量（P0-07 §8.2）。

这些不是「ConsentService 的单元测试」，是**硬约束的可执行形式**。
每条测试对应 CLAUDE.md 里的一条硬约束，注释里写明是哪一条。
改这些测试之前先改硬约束，反过来不行。
"""

from __future__ import annotations

import pytest

from cogniwork.consent.models import ConsentAction, ConsentDecision, ConsentState, Risk
from cogniwork.consent.service import ConsentService, InMemoryConsentStore

USER = "user-1"


def _service(registry, states=None):
    store = InMemoryConsentStore()
    for state in states or ():
        store.set(state)
    return ConsentService(store, registry)


def _granted(scope_key: str, *, always_allow: bool = False) -> ConsentState:
    return ConsentState(USER, scope_key, ConsentAction.GRANTED, always_allow)


# ── 硬约束 4：risk=irreversible 永远逐次审批 ──


def test_irreversible_always_requires_approval_even_when_always_allow(registry):
    """硬约束 4。

    这是最容易被「优化掉」的一条：用户抱怨每次发邮件都要点确认，
    最自然的修法就是让「始终允许」对它生效。这条测试是那次修改的拦截点。
    """
    for spec in registry.by_risk(Risk.IRREVERSIBLE):
        svc = _service(registry, [_granted(spec.key, always_allow=True)])
        decision = svc.check(USER, spec.key, Risk.IRREVERSIBLE)
        assert decision is ConsentDecision.REQUIRE_APPROVAL, (
            f"{spec.key}: 已授权且 always_allow=True 时仍必须逐次审批"
        )


def test_irreversible_tool_under_write_scope_still_requires_approval(registry):
    """工具的 risk 高于 Scope 的 risk 时，以工具为准。

    真实场景：tool:gcal:write 的 Scope risk 是 write，但它覆盖的
    delete_event / send_invites 是 irreversible（P0-05 §4.2）。
    如果 check 用 Scope 的 risk，删除日程会被「始终允许」放过去。
    """
    scope_key = "tool:gcal:write"
    svc = _service(registry, [_granted(scope_key, always_allow=True)])

    assert svc.check(USER, scope_key, Risk.WRITE) is ConsentDecision.ALLOW
    assert svc.check(USER, scope_key, Risk.IRREVERSIBLE) is ConsentDecision.REQUIRE_APPROVAL, (
        "共享 Scope 的 irreversible 工具必须逐次审批"
    )


# ── 硬约束 1：默认关闭一切采集 ──


def test_everything_is_denied_by_default(registry):
    """硬约束 1：没有任何授权记录时，所有 Scope 一律 DENY。

    遍历整个注册表，不允许有任何一个 Scope 在零授权状态下放行。
    新增 Scope 时这条自动覆盖到，不需要有人记得补测试。
    """
    svc = _service(registry)
    for spec in registry:
        for risk in (Risk.READ, Risk.WRITE, Risk.IRREVERSIBLE):
            assert svc.check(USER, spec.key, risk) is ConsentDecision.DENY, (
                f"{spec.key}: 未授权状态下不得放行（risk={risk}）"
            )


def test_revoked_consent_denies(registry):
    """撤销后立即失效。append-only 模型下撤销是追加 revoked 记录（P0-07 §4）。"""
    scope_key = "tool:notion:read"
    store = InMemoryConsentStore()
    store.set(ConsentState(USER, scope_key, ConsentAction.REVOKED, always_allow=True))
    svc = ConsentService(store, registry)
    assert svc.check(USER, scope_key, Risk.READ) is ConsentDecision.DENY


def test_expired_consent_denies(registry):
    """文案改版扩大采集范围时状态置为 expired，需重新征求同意（P0-07 §6.3）。"""
    scope_key = "tool:notion:read"
    store = InMemoryConsentStore()
    store.set(ConsentState(USER, scope_key, ConsentAction.EXPIRED, always_allow=True))
    svc = ConsentService(store, registry)
    assert svc.check(USER, scope_key, Risk.READ) is ConsentDecision.DENY


# ── 硬约束 2：绕过 Scope 的能力调用是缺陷 ──


def test_unregistered_scope_is_denied(registry):
    """未在注册表登记的 Scope 一律拒绝。

    选择 DENY 而不是抛异常：调用方拿到 DENY 会走降级路径，
    抛异常则把一次配置疏漏变成用户可见的故障。
    """
    svc = _service(registry)
    assert svc.check(USER, "tool:slack:send", Risk.IRREVERSIBLE) is ConsentDecision.DENY
    assert svc.check(USER, "made:up:read", Risk.READ) is ConsentDecision.DENY


# ── 硬约束 5：零授权用户必须能走通核心路径 ──


def test_builtin_tools_need_no_scope(registry):
    """scope_key=None 直接放行 —— L1 单次任务代劳无需授权。

    「注册 → 上传 xlsx → 整理成周报 → 下载产物」全程走这一支。
    这是零授权 E2E（P0-07 §8.3）在单元层面的对应物。
    """
    svc = _service(registry)
    assert svc.check(USER, None, Risk.READ) is ConsentDecision.ALLOW


# ── 授权后的正常路径 ──


def test_granted_without_always_allow_requires_approval(registry):
    """已授权但未选「始终允许」的写操作，仍逐次审批。"""
    scope_key = "tool:notion:write"
    svc = _service(registry, [_granted(scope_key, always_allow=False)])
    assert svc.check(USER, scope_key, Risk.WRITE) is ConsentDecision.REQUIRE_APPROVAL


def test_granted_with_always_allow_permits_non_irreversible(registry):
    scope_key = "tool:notion:write"
    svc = _service(registry, [_granted(scope_key, always_allow=True)])
    assert svc.check(USER, scope_key, Risk.WRITE) is ConsentDecision.ALLOW


def test_granted_read_scope_allows_read_after_always_allow(registry):
    scope_key = "tool:gmail:read"
    svc = _service(registry, [_granted(scope_key, always_allow=True)])
    assert svc.check(USER, scope_key, Risk.READ) is ConsentDecision.ALLOW


# ── 授权互不牵连 ──


def test_granting_read_does_not_grant_write(registry):
    """G2 读写严格分离：连接 Gmail 只读，绝不隐含发送能力（P0-05 §1）。"""
    svc = _service(registry, [_granted("tool:gmail:read", always_allow=True)])
    assert svc.check(USER, "tool:gmail:read", Risk.READ) is ConsentDecision.ALLOW
    assert svc.check(USER, "tool:gmail:send", Risk.IRREVERSIBLE) is ConsentDecision.DENY
    assert svc.check(USER, "tool:gmail:write", Risk.WRITE) is ConsentDecision.DENY


def test_granting_one_scope_does_not_grant_another_target(registry):
    """规则 2：desktop:excel:automate 与 desktop:mail:automate 是两个独立开关。"""
    svc = _service(registry, [_granted("desktop:excel:automate", always_allow=True)])
    assert svc.check(USER, "desktop:excel:automate", Risk.WRITE) is ConsentDecision.ALLOW
    assert svc.check(USER, "desktop:mail:automate", Risk.IRREVERSIBLE) is ConsentDecision.DENY


def test_consent_is_per_user(registry):
    svc = _service(registry, [_granted("tool:notion:read", always_allow=True)])
    assert svc.check("user-2", "tool:notion:read", Risk.READ) is ConsentDecision.DENY


# ── DENY 时必须能给出降级方案 ──


def test_denied_scope_can_explain_a_fallback(registry):
    """00-conventions.md §4：DENY 后 Runtime 要向用户解释并给出降级方案。

    每个已注册 Scope 都必须能回答「不开启可以怎么做」，否则 DENY
    就只是一句「不行」，自愿模型在体验上不成立。
    """
    svc = _service(registry)
    for spec in registry:
        fallback = svc.degraded_behavior(spec.key, "en-US", "en-US")
        assert fallback and fallback.strip(), f"{spec.key}: 无法给出降级说明"


def test_degraded_behavior_falls_back_when_locale_missing(registry):
    """缺翻译时回落而不是崩溃 —— 缺失由 CI 拦，运行时不该因此故障。"""
    svc = _service(registry)
    assert svc.degraded_behavior("tool:gmail:read", "fr-FR", "en-US")


def test_degraded_behavior_of_unknown_scope_is_none(registry):
    svc = _service(registry)
    assert svc.degraded_behavior("nope:nope:read", "en-US", "en-US") is None


# ── 决策顺序 ──


@pytest.mark.parametrize(
    ("action", "always_allow", "risk", "expected"),
    [
        (ConsentAction.GRANTED, False, Risk.READ, ConsentDecision.REQUIRE_APPROVAL),
        (ConsentAction.GRANTED, True, Risk.READ, ConsentDecision.ALLOW),
        (ConsentAction.GRANTED, True, Risk.WRITE, ConsentDecision.ALLOW),
        (ConsentAction.GRANTED, True, Risk.IRREVERSIBLE, ConsentDecision.REQUIRE_APPROVAL),
        (ConsentAction.GRANTED, False, Risk.IRREVERSIBLE, ConsentDecision.REQUIRE_APPROVAL),
        (ConsentAction.REVOKED, True, Risk.READ, ConsentDecision.DENY),
    ],
)
def test_decision_matrix(registry, action, always_allow, risk, expected):
    """完整决策矩阵 —— 把 P0-07 §6.2 的伪代码逐格钉住。"""
    scope_key = "tool:notion:write"
    store = InMemoryConsentStore()
    store.set(ConsentState(USER, scope_key, action, always_allow))
    svc = ConsentService(store, registry)
    assert svc.check(USER, scope_key, risk) is expected
