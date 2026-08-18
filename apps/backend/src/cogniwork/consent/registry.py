"""Scope 注册表加载与校验。

单一事实来源是 config/scopes.yaml。本模块在**进程启动时**加载并校验它，
校验失败直接抛异常 —— 一个元数据不全的 Scope 宁可让服务起不来，
也不能让它带着空的 degraded_behavior 跑到用户面前。

约定见 00-conventions.md §3、P0-07 §3。
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .models import Risk, ScopeCopy, ScopeSpec, TrustLevel

KEY_PATTERN = re.compile(r"^[a-z0-9_]+:[a-z0-9_*]+:[a-z0-9_]+$")

# degraded_behavior 不得是这些占位符（P0-07 §8.2）
PLACEHOLDER_PATTERN = re.compile(r"^\s*(todo|tbd|n/?a|none|无|待定|-+|\?+)\s*$", re.IGNORECASE)

# degraded_behavior 不得表达「功能不可用」—— 这是硬约束 6，不是文案偏好
UNAVAILABLE_PATTERN = re.compile(
    r"(功能不可用|无法使用|不可用|not available|unavailable|cannot be used|no fallback)",
    re.IGNORECASE,
)

# 授权文案中的诱导性表述（00-conventions.md §5、P0-07 §8.2）
INDUCEMENT_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"完整体验",
        r"解锁",
        r"才能",
        r"必须开启",
        r"unlock",
        r"full experience",
        r"you (?:must|need to) enable",
        r"only works if you",
    )
]


class RegistryError(Exception):
    """注册表本身有问题 —— 配置错误，不是运行时错误。"""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise RegistryError(msg)


def default_registry_path() -> Path:
    """定位 config/scopes.yaml。

    优先取环境变量 ``COGNIWORK_SCOPES_PATH``（部署时目录结构与仓库不同）；
    否则从本文件向上逐层找 ``config/scopes.yaml``。

    不写死层数 —— 目录深度会随重构变化，而那种失败发生在启动时、
    错误信息又指向一个不存在的路径，排查起来比它值得的时间长。
    """
    override = os.environ.get("COGNIWORK_SCOPES_PATH")
    if override:
        return Path(override)

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "config" / "scopes.yaml"
        if candidate.is_file():
            return candidate

    # 找不到时返回仓库根的期望位置，让错误信息指向「应该在哪」
    return Path(__file__).resolve().parents[5] / "config" / "scopes.yaml"


class ScopeRegistry:
    """已校验的 Scope 集合。"""

    def __init__(self, scopes: dict[str, ScopeSpec], vocabularies: dict[str, list[str]]) -> None:
        self._scopes = scopes
        self.vocabularies = vocabularies

    def __contains__(self, key: str) -> bool:
        return key in self._scopes

    def __len__(self) -> int:
        return len(self._scopes)

    def __iter__(self):
        return iter(self._scopes.values())

    def get(self, key: str) -> ScopeSpec | None:
        return self._scopes.get(key)

    def require(self, key: str) -> ScopeSpec:
        spec = self._scopes.get(key)
        if spec is None:
            raise RegistryError(
                f"未注册的 Scope: {key!r}。"
                "所有需要授权的能力必须先在 config/scopes.yaml 登记（硬约束 2）。"
            )
        return spec

    def keys(self) -> list[str]:
        return sorted(self._scopes)

    def by_risk(self, risk: Risk) -> list[ScopeSpec]:
        return [s for s in self._scopes.values() if s.risk is risk]


def _parse_copy(key: str, raw: Any) -> dict[str, ScopeCopy]:
    _require(isinstance(raw, dict) and raw, f"{key}: copy 缺失或为空")
    out: dict[str, ScopeCopy] = {}
    for locale, block in raw.items():
        _require(isinstance(block, dict), f"{key}: copy.{locale} 必须是对象")
        fields = {}
        for field in ("display_name", "collects", "retention", "degraded_behavior"):
            value = block.get(field)
            _require(
                isinstance(value, str) and value.strip(),
                f"{key}: copy.{locale}.{field} 缺失或为空 —— 六项元数据必须齐全（硬约束 2）",
            )
            fields[field] = value.strip()

        degraded = fields["degraded_behavior"]
        _require(
            not PLACEHOLDER_PATTERN.match(degraded),
            f"{key}: copy.{locale}.degraded_behavior 是占位符 {degraded!r}",
        )
        _require(
            not UNAVAILABLE_PATTERN.search(degraded),
            f"{key}: copy.{locale}.degraded_behavior 表达了「功能不可用」—— "
            "硬约束 6 不允许。若该功能本身就是此 Scope 的直接产物，"
            "说明这个能力的划分方式有问题，应重新拆分 Scope。",
        )

        for field in ("display_name", "collects", "retention", "degraded_behavior"):
            for pattern in INDUCEMENT_PATTERNS:
                _require(
                    not pattern.search(fields[field]),
                    f"{key}: copy.{locale}.{field} 含诱导性表述（匹配 {pattern.pattern!r}）",
                )

        out[locale] = ScopeCopy(**fields)
    return out


def load_registry(path: Path | None = None) -> ScopeRegistry:
    """加载并校验 config/scopes.yaml。校验不通过直接抛 RegistryError。"""
    path = path or default_registry_path()
    _require(path.is_file(), f"Scope 注册表不存在: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    _require(isinstance(raw, dict), f"{path}: 顶层必须是对象")

    vocab = raw.get("vocabularies") or {}
    _require(isinstance(vocab, dict), f"{path}: vocabularies 必须是对象")
    for name in ("domain", "capability", "risk", "trust_level"):
        _require(
            isinstance(vocab.get(name), list) and vocab[name],
            f"{path}: vocabularies.{name} 缺失",
        )

    # 词表与代码里的枚举必须一致，否则改了一边忘了另一边不会有人发现
    _require(
        set(vocab["risk"]) == {r.value for r in Risk},
        f"vocabularies.risk 与 models.Risk 不一致: {vocab['risk']} vs {[r.value for r in Risk]}",
    )
    _require(
        set(vocab["trust_level"]) == {t.value for t in TrustLevel},
        "vocabularies.trust_level 与 models.TrustLevel 不一致",
    )

    entries = raw.get("scopes")
    _require(isinstance(entries, list) and entries, f"{path}: scopes 缺失或为空")

    scopes: dict[str, ScopeSpec] = {}
    for entry in entries:
        _require(isinstance(entry, dict), f"{path}: scopes 的每一项必须是对象")
        key = entry.get("key")
        _require(isinstance(key, str) and key, f"{path}: 有一条 scope 缺 key")
        _require(key not in scopes, f"重复的 Scope key: {key}")
        _require(
            bool(KEY_PATTERN.match(key)),
            f"{key}: 不符合 <domain>:<target>:<capability> 格式（00-conventions.md §3）",
        )

        domain, _, capability = key.split(":", 1)[0], None, key.rsplit(":", 1)[1]
        _require(domain in vocab["domain"], f"{key}: domain {domain!r} 不在受控词表内")
        _require(
            capability in vocab["capability"],
            f"{key}: capability {capability!r} 不在受控词表内 {vocab['capability']}",
        )

        risk_raw = entry.get("risk")
        _require(risk_raw in vocab["risk"], f"{key}: risk {risk_raw!r} 非法")
        trust_raw = entry.get("trust_level")
        _require(trust_raw in vocab["trust_level"], f"{key}: trust_level {trust_raw!r} 非法")

        scopes[key] = ScopeSpec(
            key=key,
            trust_level=TrustLevel(trust_raw),
            risk=Risk(risk_raw),
            copy=_parse_copy(key, entry.get("copy")),
            third_party_scopes=tuple(entry.get("third_party_scopes") or ()),
            requires_os_permission=tuple(entry.get("requires_os_permission") or ()),
            google_tier=entry.get("google_tier"),
            review_status=entry.get("review_status", "pending"),
            consent_text_version=str(entry.get("consent_text_version") or "1"),
        )

    return ScopeRegistry(scopes, {k: list(v) for k, v in vocab.items()})


@lru_cache(maxsize=1)
def get_registry() -> ScopeRegistry:
    """进程级单例。注册表是编译期常量，运行时不可动态新增（P0-07 §3）。"""
    return load_registry()
