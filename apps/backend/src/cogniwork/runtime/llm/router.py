"""按配置表路由模型（P0-03 §7）。没有密钥时回落到 stub。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from cogniwork.core.config import Settings, get_settings
from cogniwork.core.paths import find_config_file

from .clients import AnthropicClient, OpenAICompatClient
from .stub import StubLLM
from .types import LLMClient


@dataclass(frozen=True, slots=True)
class RoutingRequest:
    task_intent: str | None
    context_tokens: int
    needs_vision: bool
    needs_tool_use: bool
    latency_class: Literal["interactive", "background"]
    cost_tier: Literal["economy", "standard", "premium"]


@dataclass(frozen=True, slots=True)
class ModelRef:
    vendor: str
    model: str


class ModelRouter:
    def __init__(self, settings: Settings | None = None, path: Path | None = None) -> None:
        self._settings = settings or get_settings()
        self._path = path or _routes_path(self._settings)
        self._data = _load(self._path)

    def choose(self, request: RoutingRequest) -> ModelRef:
        if _use_stub(self._settings):
            return ModelRef("stub", "stub-local")
        for route in self._data.get("routes", []):
            if "default" in route:
                continue
            match = route.get("match") or {}
            if _matches(match, request):
                return self._resolve(route["model"])
        default = next((r["default"] for r in self._data.get("routes", []) if "default" in r), None)
        if default:
            return self._resolve(default)
        return ModelRef("stub", "stub-local")

    def client_for(self, request: RoutingRequest) -> LLMClient:
        chosen = self.choose(request)
        return build_client(chosen, self._settings)

    def _resolve(self, dotted: str) -> ModelRef:
        provider_name, slot = dotted.split(".", 1)
        providers = self._data.get("providers") or {}
        provider = providers.get(provider_name) or {}
        vendor = str(provider.get("vendor") or "stub")
        model = str(provider.get(slot) or provider.get("standard") or "stub-local")
        if _use_stub(self._settings) or not _vendor_ready(vendor, self._settings):
            fallback = providers.get("fallback") or {}
            fallback_vendor = str(fallback.get("vendor") or "")
            if fallback_vendor and _vendor_ready(fallback_vendor, self._settings):
                return ModelRef(
                    fallback_vendor, str(fallback.get(slot) or fallback.get("standard"))
                )
            return ModelRef("stub", "stub-local")
        return ModelRef(vendor, model)


def build_client(ref: ModelRef, settings: Settings) -> LLMClient:
    if ref.vendor == "anthropic" and settings.anthropic_api_key:
        return AnthropicClient(settings.anthropic_api_key, ref.model)
    if ref.vendor == "openai" and settings.openai_api_key:
        return OpenAICompatClient(settings.openai_api_key, ref.model)
    return StubLLM()


def _use_stub(settings: Settings) -> bool:
    if settings.llm_provider == "stub":
        return True
    if settings.llm_provider == "anthropic":
        return not settings.anthropic_api_key
    if settings.llm_provider == "openai":
        return not settings.openai_api_key
    return not settings.anthropic_api_key and not settings.openai_api_key


def _vendor_ready(vendor: str, settings: Settings) -> bool:
    if vendor == "anthropic":
        return bool(settings.anthropic_api_key)
    if vendor == "openai":
        return bool(settings.openai_api_key)
    return vendor == "stub"


def _matches(match: dict[str, Any], request: RoutingRequest) -> bool:
    if "needs_vision" in match and bool(match["needs_vision"]) != request.needs_vision:
        return False
    if "needs_tool_use" in match and bool(match["needs_tool_use"]) != request.needs_tool_use:
        return False
    if "latency_class" in match and match["latency_class"] != request.latency_class:
        return False
    if "cost_tier" in match and match["cost_tier"] != request.cost_tier:
        return False
    if "context_tokens_gt" in match:
        if not (request.context_tokens > int(match["context_tokens_gt"])):
            return False
    return True


def _routes_path(settings: Settings) -> Path:
    if settings.model_routes_path:
        return Path(settings.model_routes_path)
    return find_config_file("model_routes.yaml", "COGNIWORK_MODEL_ROUTES_PATH")


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"routes": [{"default": "stub.standard"}], "providers": {"stub": {"vendor": "stub"}}}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    return data
