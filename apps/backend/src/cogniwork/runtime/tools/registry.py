"""工具注册表。新增一类工具只加 Executor，不改 Runtime 循环。"""

from __future__ import annotations

from .builtin import BUILTIN_TOOLS, BuiltinExecutor
from .spec import Executor, ToolSpec


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._executors: dict[str, Executor] = {}

    def register(self, spec: ToolSpec, executor: Executor) -> None:
        self._specs[spec.name] = spec
        self._executors[spec.name] = executor

    def get(self, name: str) -> tuple[ToolSpec, Executor] | None:
        spec = self._specs.get(name)
        if spec is None:
            return None
        return spec, self._executors[name]

    def specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def __iter__(self):
        return iter(self._specs.values())


def build_builtin_registry() -> ToolRegistry:
    registry = ToolRegistry()
    executor = BuiltinExecutor()
    for spec in BUILTIN_TOOLS:
        registry.register(spec, executor)
    return registry
