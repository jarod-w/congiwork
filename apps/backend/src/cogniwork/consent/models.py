"""Consent 领域模型。

这些类型是 Scope 注册表（config/scopes.yaml）与运行时之间的契约。
枚举值必须与 scopes.yaml 的 `vocabularies` 一致 —— 由 registry 加载时交叉校验，
不要在两边各改各的。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Risk(StrEnum):
    """能力的风险等级（00-conventions.md §3）。

    判定原则：「这个动作出错后，用户能自己收拾干净吗？」不能 → IRREVERSIBLE。
    """

    READ = "read"
    WRITE = "write"
    IRREVERSIBLE = "irreversible"


class TrustLevel(StrEnum):
    """信任爬坡层级（00-conventions.md §3.1）。"""

    L1 = "L1"  # 单次任务代劳，无需 Scope
    L2 = "L2"  # 只读工具
    L3 = "L3"  # 执行类工具 / 本地应用操作
    L4 = "L4"  # 结构化日志采集（Phase 2）


class ConsentAction(StrEnum):
    """consent_record 的动作（P0-07 §4）。append-only，撤销是追加不是删除。"""

    GRANTED = "granted"
    REVOKED = "revoked"
    EXPIRED = "expired"


class ConsentDecision(StrEnum):
    """ConsentService.check 的三种结果（P0-07 §6.2）。"""

    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class ScopeCopy:
    """一个 Scope 面向用户的四段文案。

    这四段直接进授权卡片（P0-07 §6.1），是整个隐私模型的承重结构 ——
    用户是读完它才点同意的。因此它们不是技术描述，也不允许留空。
    """

    display_name: str
    collects: str
    retention: str
    degraded_behavior: str


@dataclass(frozen=True, slots=True)
class ScopeSpec:
    """注册表中的一条 Scope 定义。"""

    key: str
    trust_level: TrustLevel
    risk: Risk
    copy: dict[str, ScopeCopy]  # locale -> copy
    third_party_scopes: tuple[str, ...] = ()
    requires_os_permission: tuple[str, ...] = ()
    google_tier: str | None = None
    review_status: str = "pending"

    @property
    def domain(self) -> str:
        return self.key.split(":", 1)[0]

    @property
    def target(self) -> str:
        return self.key.split(":")[1]

    @property
    def capability(self) -> str:
        return self.key.rsplit(":", 1)[1]

    def copy_for(self, locale: str, fallback: str) -> ScopeCopy:
        """取指定语言的文案，缺失时回落。

        回落是有意为之而不是掩盖问题：缺失由 tests/guards 在 CI 里拦截，
        运行时不应该因为某个语言没翻译就崩掉。
        """
        if locale in self.copy:
            return self.copy[locale]
        return self.copy[fallback]


@dataclass(frozen=True, slots=True)
class ConsentState:
    """某用户对某 Scope 的当前授权状态。"""

    user_id: str
    scope_key: str
    action: ConsentAction
    always_allow: bool

    @property
    def is_granted(self) -> bool:
        return self.action is ConsentAction.GRANTED
