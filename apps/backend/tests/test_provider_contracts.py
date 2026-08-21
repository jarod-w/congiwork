"""连接器契约测试（P0-05 M6）。

在此之前，四个 provider 的请求 / 响应形状只被别处单测里的 stub 顺带覆盖 ——
stub 和适配器是一起改的，所以形状改了也不会有任何测试变红。

这里换一种约束：`tests/contracts/upstream_contracts.json` 把「我们往上游发什么、
读上游的哪些字段」写死成一份可审阅的清单，三条断言压在上面：

1. **请求形状**：方法、URL、参数名与请求体字段名逐个比对。适配器改了发出去的
   字段名，这里立刻红。
2. **依赖字段是承重的**：把 `depends_on` 里的字段从响应里去掉，结果必须变。
   这条防的是「清单写着依赖 items，其实早就不读了」这种清单腐烂。
3. **目录与适配器不脱节**：catalog 里的每个工具都必须有契约条目，且必须真的
   有实现（不落到 "Unknown ... tool" 那一支）。

**能力边界要说清楚**：离线测试检测不出上游今天改了字段 —— 没有任何离线测试能。
它买到的是「上游发了变更公告时，只改这一个文件，然后由测试告诉你哪些适配器要动」。
第 3 条则把 catalog 和适配器的漂移变成 CI 问题，而这一类漂移完全在我们自己手里。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cogniwork.tools.catalog import load_catalog
from cogniwork.tools.http import HttpResponse
from cogniwork.tools.providers import invoke_provider

CONTRACTS: dict[str, Any] = {
    key: value
    for key, value in json.loads(
        (Path(__file__).parent / "contracts" / "upstream_contracts.json").read_text(
            encoding="utf-8"
        )
    ).items()
    if not key.startswith("_")
}

TOKEN = "cw-canary-access"


class ContractTransport:
    """回放录下来的响应，同时比对发出去的请求。"""

    def __init__(self, expected: dict[str, Any], response: dict[str, Any]) -> None:
        self._expected = expected
        self._response = response
        self.seen: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> HttpResponse:
        self.seen.append({"method": method, "url": url, "params": params, "json": json_body})
        assert method.upper() == self._expected["method"], (
            f"HTTP 方法与契约不符：{method} != {self._expected['method']}"
        )
        assert url == self._expected["url"], f"URL 与契约不符：\n  {url}\n  {self._expected['url']}"
        if "params" in self._expected:
            sent = {k: v for k, v in (params or {}).items() if v is not None}
            assert sent == self._expected["params"], (
                f"查询参数与契约不符：\n  {sent}\n  {self._expected['params']}"
            )
        if "json" in self._expected:
            sent_body = _prune(json_body or {})
            assert sent_body == self._expected["json"], (
                f"请求体与契约不符：\n  {sent_body}\n  {self._expected['json']}"
            )
        if "json_keys" in self._expected:
            # raw 是 base64 后的 MIME，比对字段名而不是内容。
            assert sorted(json_body or {}) == sorted(self._expected["json_keys"])
        # Authorization 必须带上，但不比对值（凭据不进断言，硬约束 9）
        assert (headers or {}).get("Authorization"), "上游调用必须带 Authorization"
        return HttpResponse(200, dict(self._response), {})


def _prune(value: Any) -> Any:
    """去掉 None 字段。适配器对可选参数发 None，契约里不写它们。"""
    if isinstance(value, dict):
        return {k: _prune(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_prune(item) for item in value]
    return value


def _call(name: str, contract: dict[str, Any], response: dict[str, Any] | None = None):
    provider, mcp_name = name.split(".", 1)
    transport = ContractTransport(
        contract["request"], response if response is not None else contract["response"]
    )
    return invoke_provider(provider, mcp_name, contract["arguments"], TOKEN, transport)


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_request_and_response_match_the_recorded_contract(name: str):
    contract = CONTRACTS[name]
    result = _call(name, contract)
    expect = contract["expect"]
    assert result.ok is expect["ok"], result.content
    assert result.name == name
    for fragment in expect.get("content_contains", []):
        assert fragment in result.content, (
            f"{name}: 结果文案里应包含 {fragment!r}：{result.content}"
        )
    for key, value in (expect.get("data") or {}).items():
        assert result.data.get(key) == value, f"{name}: data[{key!r}] 与契约不符：{result.data}"


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_declared_response_dependencies_are_load_bearing(name: str):
    """去掉 depends_on 里的字段，结果必须变 —— 否则那条声明已经过期。"""
    contract = CONTRACTS[name]
    baseline = _call(name, contract)
    for field in contract["depends_on"]:
        stripped = {k: v for k, v in contract["response"].items() if k != field}
        degraded = _call(name, contract, stripped)
        assert (degraded.content, degraded.data) != (baseline.content, baseline.data), (
            f"{name}: 契约声明依赖响应字段 {field!r}，但去掉它结果没变。"
            "要么适配器不再读这个字段（更新契约），要么依赖声明写错了。"
        )


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_an_empty_upstream_response_does_not_raise(name: str):
    """上游返回意料之外的空响应时，适配器要收成 ToolResult，不能把异常抛给 Runtime。"""
    contract = CONTRACTS[name]
    result = _call(name, contract, {})
    assert isinstance(result.ok, bool)
    assert isinstance(result.content, str)


def test_every_catalog_tool_has_a_contract():
    """新增连接器工具必须同时录一份契约，否则它的请求形状又回到无人守护的状态。"""
    catalog_names = {tool.name for provider in load_catalog().providers for tool in provider.tools}
    missing = sorted(catalog_names - set(CONTRACTS))
    extra = sorted(set(CONTRACTS) - catalog_names)
    assert not missing, f"这些工具在 tool_catalog.yaml 里，但没有契约条目：{missing}"
    assert not extra, f"这些契约条目在 catalog 里已经不存在了：{extra}"


def test_every_catalog_tool_is_actually_implemented():
    """catalog 登记了但 providers.py 没实现，运行时表现是一句 'Unknown ... tool'。

    那种情况下 LLM 会拿到一个可用工具的名字然后失败一次 —— 目录与实现的漂移
    应该在 CI 里发现，不是在用户任务里。
    """
    unimplemented = []
    for provider in load_catalog().providers:
        for tool in provider.tools:
            contract = CONTRACTS[tool.name]
            result = _call(tool.name, contract)
            if result.content.startswith("Unknown "):
                unimplemented.append(tool.name)
    assert not unimplemented, f"catalog 登记了但没有实现：{unimplemented}"
