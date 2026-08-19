"""工具调用链：闸门 → Executor → 审计。Executor 看不到闸门内部。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from cogniwork.core.config import get_settings
from cogniwork.runtime.digest import digest_args

from .hook import Gate, fallback_copy, gate_tool_call
from .registry import ToolRegistry
from .spec import ToolResult, ToolSpec


class ToolRouter:
    def __init__(
        self,
        registry: ToolRegistry,
        consent: Any,
        audit: Any,
    ) -> None:
        self._registry = registry
        self._consent = consent
        self._audit = audit

    def resolve(self, name: str) -> ToolSpec | None:
        found = self._registry.get(name)
        return None if found is None else found[0]

    def invoke(
        self,
        *,
        user_id: str,
        name: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> ToolResult:
        found = self._registry.get(name)
        if found is None:
            return ToolResult(name, False, f"Unknown tool: {name}")
        spec, executor = found
        settings = get_settings()
        locale = settings.default_locale
        fallback = settings.fallback_locale
        decision = gate_tool_call(self._consent, user_id, spec)
        digest = digest_args(arguments)
        surface = str(context.get("surface") or "web")
        task_id = context.get("task_id")
        step_id = context.get("step_id")

        if decision is Gate.BLOCKED:
            copy = fallback_copy(self._consent, spec, locale, fallback)
            self._audit.record(
                user_id=user_id,
                task_id=str(task_id) if task_id else None,
                step_id=str(step_id) if step_id else None,
                scope_key=spec.scope_key,
                surface=surface,
                action=spec.name,
                target_digest=digest,
                result="denied",
            )
            message = "This action is not enabled. " + (
                copy or "You can paste the needed content instead."
            )
            return ToolResult(name, False, message, {"scope_key": spec.scope_key}, blocked=True)

        if decision is Gate.NEEDS_APPROVAL:
            # 审批中断是阶段 3（P0-03 M4）。本阶段拒绝执行，避免未审批就出网。
            self._audit.record(
                user_id=user_id,
                task_id=str(task_id) if task_id else None,
                step_id=str(step_id) if step_id else None,
                scope_key=spec.scope_key,
                surface=surface,
                action=spec.name,
                target_digest=digest,
                result="denied",
            )
            return ToolResult(
                name,
                False,
                "This action needs your confirmation before I can run it.",
                {"scope_key": spec.scope_key},
                needs_approval=True,
            )

        started = perf_counter()
        try:
            result = executor.invoke(spec, arguments, context)
        except Exception as exc:
            duration = int((perf_counter() - started) * 1000)
            self._audit.record(
                user_id=user_id,
                task_id=str(task_id) if task_id else None,
                step_id=str(step_id) if step_id else None,
                scope_key=spec.scope_key,
                surface=surface,
                action=spec.name,
                target_digest=digest,
                result="failed",
                error_code="upstream_error",
                duration_ms=duration,
            )
            return ToolResult(
                name,
                False,
                "The tool failed. I recorded the error.",
                {"error": type(exc).__name__},
            )

        duration = int((perf_counter() - started) * 1000)
        self._audit.record(
            user_id=user_id,
            task_id=str(task_id) if task_id else None,
            step_id=str(step_id) if step_id else None,
            scope_key=spec.scope_key,
            surface=surface,
            action=spec.name,
            target_digest=digest,
            result="allowed" if result.ok else "failed",
            duration_ms=duration,
        )
        return result
