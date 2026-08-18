"""权限闸门 —— ConsentService.check 的唯一调用方。

硬约束 3：检查点只在 Agent Runtime 的工具调用链上。
各 Executor 拿不到决策枚举，也看不到这个模块以外的判定符号。

本文件必须列入 tests/guards/test_no_bypass.py 的 CONSENT_OWNED。
"""

from __future__ import annotations

from enum import StrEnum

from cogniwork.consent.models import ConsentDecision
from cogniwork.consent.service import ConsentService

from .spec import ToolSpec


class Gate(StrEnum):
    """给调用链看的放行结果。有意不用 ConsentDecision 这个名字，
    以免 Executor 侧「顺手」依赖检查点的词汇。"""

    PROCEED = "proceed"
    BLOCKED = "blocked"
    NEEDS_APPROVAL = "needs_approval"


def gate_tool_call(service: ConsentService, user_id: str, spec: ToolSpec) -> Gate:
    decision = service.check(user_id, spec.scope_key, spec.risk)
    if decision is ConsentDecision.ALLOW:
        return Gate.PROCEED
    if decision is ConsentDecision.REQUIRE_APPROVAL:
        return Gate.NEEDS_APPROVAL
    return Gate.BLOCKED


def fallback_copy(
    service: ConsentService, spec: ToolSpec, locale: str, fallback: str
) -> str | None:
    if spec.scope_key is None:
        return None
    return service.degraded_behavior(spec.scope_key, locale, fallback)
