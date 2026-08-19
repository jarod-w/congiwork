"""ConsentService —— 权限检查的唯一检查点。

硬约束 3：权限检查只在 Agent Runtime 的工具调用链上进行（P0-03 §5 调用本模块）。
**各 Executor 内部不做也不能做权限判断。**

这不是风格偏好。散落在各处的权限判断有两个后果：一是漏掉一处就是一个越权通道，
二是没有任何单点能回答「这次调用为什么被允许」。审计的可信度建立在检查点唯一之上。

守护测试见 tests/guards/。
"""

from __future__ import annotations

from typing import Any, Protocol

from .models import ConsentAction, ConsentDecision, ConsentState, Risk
from .registry import ScopeRegistry, get_registry
from .store import InMemoryConsentStore

__all__ = ["ConsentService", "ConsentStore", "InMemoryConsentStore", "build_consent_service"]


class ConsentStore(Protocol):
    """当前授权状态的读取接口。

    实现（P0-07 §4）：Redis `consent:{user_id}` hash 优先，未命中回落
    `consent_current` 物化视图。写入走 append()，见 consent/store.py。
    """

    def current(self, user_id: str, scope_key: str) -> ConsentState | None: ...

    def append(
        self,
        *,
        user_id: str,
        scope_key: str,
        action: ConsentAction,
        always_allow: bool,
        surface: str,
        consent_text_version: str,
        device_info: dict[str, Any] | None = None,
        ip_hash: str | None = None,
    ) -> None: ...


def build_consent_service(
    store: ConsentStore, registry: ScopeRegistry | None = None
) -> ConsentService:
    return ConsentService(store, registry)


class ConsentService:
    """运行时授权检查（P0-07 §6.2）。"""

    def __init__(self, store: ConsentStore, registry: ScopeRegistry | None = None) -> None:
        self._store = store
        self._registry = registry or get_registry()

    def check(self, user_id: str, scope_key: str | None, risk: Risk) -> ConsentDecision:
        """判定一次工具调用是否可以执行。

        Args:
            user_id: 调用者。
            scope_key: 该工具声明的 Scope；``None`` 表示 builtin 只读工具（L1，无需授权）。
            risk: **这次调用的工具**的风险等级，不是 Scope 的风险等级。

                两者可以不同，这是有意的：一个 Scope 覆盖多个同级工具，
                但其中个别工具可能是 irreversible。例如 ``tool:gcal:write``
                的 risk 是 write，而它覆盖的 ``delete_event`` 是 irreversible ——
                后者必须逐次审批。若这里用 Scope 的 risk，删除日程就会被
                「始终允许」放过去。见 P0-05 §4.2 的说明。

        Returns:
            ALLOW / REQUIRE_APPROVAL / DENY。
        """
        # L1：builtin 只读工具无需 Scope。核心路径（注册 → 上传 → 得到结果）
        # 全程走这一支，这是硬约束 5 与零授权 E2E（P0-07 §8.3）成立的地方。
        if scope_key is None:
            return ConsentDecision.ALLOW

        # 未注册的 Scope 一律拒绝。绕过注册表的能力调用是缺陷（硬约束 2），
        # 这里选择拒绝而不是抛异常：调用方拿到 DENY 会走降级路径，
        # 而抛异常会让一次配置疏漏变成用户可见的故障。
        if scope_key not in self._registry:
            return ConsentDecision.DENY

        state = self._store.current(user_id, scope_key)
        if state is None or not state.is_granted:
            return ConsentDecision.DENY

        # 硬约束 4：irreversible 永远逐次审批，即使用户选了「始终允许」。
        # 这一支必须在 always_allow 判断之前，顺序不能调换。
        if risk is Risk.IRREVERSIBLE:
            return ConsentDecision.REQUIRE_APPROVAL

        if not state.always_allow:
            return ConsentDecision.REQUIRE_APPROVAL

        return ConsentDecision.ALLOW

    def degraded_behavior(self, scope_key: str, locale: str, fallback: str) -> str | None:
        """取某 Scope 的降级说明，供 DENY 时向用户解释。

        Runtime 收到 DENY 后不能只报错，必须给出「不开启也可以怎么做」
        （00-conventions.md §4）。这个方法是那句话的来源。
        """
        spec = self._registry.get(scope_key)
        if spec is None:
            return None
        return spec.copy_for(locale, fallback).degraded_behavior

    def grant(
        self,
        *,
        user_id: str,
        scope_key: str,
        skip_repeat_prompt: bool,
        surface: str,
        consent_text_version: str,
        ip_hash: str | None = None,
    ) -> None:
        """授权写入。给审批卡「以后不用再问」用，不是第二条判定路径。"""
        self._store.append(
            user_id=user_id,
            scope_key=scope_key,
            action=ConsentAction.GRANTED,
            always_allow=skip_repeat_prompt,
            surface=surface,
            consent_text_version=consent_text_version,
            ip_hash=ip_hash,
        )

    def revoke(
        self,
        *,
        user_id: str,
        scope_key: str,
        surface: str,
        consent_text_version: str | None = None,
        ip_hash: str | None = None,
    ) -> None:
        """Disconnect writes a revoke record. Runtime still only checks via check()."""
        spec = self._registry.get(scope_key)
        version = consent_text_version or (spec.consent_text_version if spec else "1")
        self._store.append(
            user_id=user_id,
            scope_key=scope_key,
            action=ConsentAction.REVOKED,
            always_allow=False,
            surface=surface,
            consent_text_version=version,
            ip_hash=ip_hash,
        )
