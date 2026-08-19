"""MCP tool catalog — ToolSpec mapping (P0-05 §4 / M1)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import yaml

from cogniwork.consent.models import Risk
from cogniwork.consent.registry import get_registry
from cogniwork.core.errors import InvalidRequest
from cogniwork.core.paths import find_config_file
from cogniwork.runtime.tools.spec import ToolSpec


@dataclass(frozen=True, slots=True)
class CatalogTool:
    name: str
    mcp_name: str
    provider: str
    description: str
    scope_key: str
    risk: Risk
    input_schema: dict[str, Any]
    preview_renderer: str | None
    timeout_s: int
    retryable: bool

    def to_spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            provider="mcp",
            description=self.description,
            input_schema=self.input_schema,
            scope_key=self.scope_key,
            risk=self.risk,
            preview_renderer=self.preview_renderer,  # type: ignore[arg-type]
            timeout_s=self.timeout_s,
            retryable=self.retryable,
        )


@dataclass(frozen=True, slots=True)
class CatalogProvider:
    id: str
    display_name: str
    oauth_kind: str
    account_label_from: str
    tools: tuple[CatalogTool, ...]

    def tool(self, name: str) -> CatalogTool | None:
        for item in self.tools:
            if item.name == name or item.mcp_name == name:
                return item
        return None


@dataclass(frozen=True, slots=True)
class ToolCatalog:
    providers: tuple[CatalogProvider, ...]

    def provider(self, provider_id: str) -> CatalogProvider:
        for item in self.providers:
            if item.id == provider_id:
                return item
        raise InvalidRequest("Unknown provider.", details={"provider": provider_id})

    def tool(self, name: str) -> CatalogTool | None:
        for provider in self.providers:
            found = provider.tool(name)
            if found is not None:
                return found
        return None

    def specs(self) -> list[ToolSpec]:
        return [tool.to_spec() for provider in self.providers for tool in provider.tools]

    def oauth_scopes_for(self, cogniwork_scopes: list[str]) -> list[str]:
        """OAuth scopes are the union of registered third-party scopes for the
        CogniWork scopes the user actually enabled — never a superset.
        """
        registry = get_registry()
        collected: list[str] = []
        for key in cogniwork_scopes:
            spec = registry.get(key)
            if spec is None:
                raise InvalidRequest("Unknown scope.", details={"scope_key": key})
            for item in spec.third_party_scopes:
                if item not in collected:
                    collected.append(item)
        return collected

    def scopes_for_provider(self, provider_id: str) -> list[str]:
        keys: list[str] = []
        provider = self.provider(provider_id)
        for tool in provider.tools:
            if tool.scope_key not in keys:
                keys.append(tool.scope_key)
        return keys


@lru_cache(maxsize=1)
def load_catalog() -> ToolCatalog:
    path = find_config_file("tool_catalog.yaml", "COGNIWORK_TOOL_CATALOG_PATH")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    providers: list[CatalogProvider] = []
    for entry in raw.get("providers") or []:
        tools: list[CatalogTool] = []
        for tool in entry.get("tools") or []:
            tools.append(
                CatalogTool(
                    name=tool["name"],
                    mcp_name=tool.get("mcp_name") or tool["name"],
                    provider=entry["id"],
                    description=tool["description"],
                    scope_key=tool["scope_key"],
                    risk=Risk(tool["risk"]),
                    input_schema=dict(tool.get("input_schema") or {"type": "object"}),
                    preview_renderer=tool.get("preview_renderer"),
                    timeout_s=int(tool.get("timeout_s") or 30),
                    retryable=bool(tool.get("retryable", True)),
                )
            )
        providers.append(
            CatalogProvider(
                id=entry["id"],
                display_name=entry["display_name"],
                oauth_kind=entry["oauth_kind"],
                account_label_from=entry.get("account_label_from") or "email",
                tools=tuple(tools),
            )
        )
    return ToolCatalog(tuple(providers))
