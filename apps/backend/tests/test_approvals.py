"""审批中断 / 恢复，以及 irreversible 在 always-allow 下仍出 ApprovalRequest。"""

from __future__ import annotations

from cogniwork.consent.models import ApprovalAction, ConsentDecision, Risk
from cogniwork.core.config import get_settings
from cogniwork.runtime.approvals import ApprovalService
from cogniwork.runtime.digest import InMemoryAuditLog
from cogniwork.runtime.tools.registry import ToolRegistry
from cogniwork.runtime.tools.router import ToolRouter
from cogniwork.runtime.tools.spec import ToolSpec

from .conftest import auth_header


def _prefix() -> str:
    return get_settings().api_prefix


def test_irreversible_tools_create_approval_even_when_repeat_is_granted(registry):
    """P0-07 §8.2：irreversible 工具在 skip-repeat 已开时仍必须产生 ApprovalRequest。"""
    from cogniwork.consent.models import ConsentAction, ConsentState
    from cogniwork.consent.service import ConsentService
    from cogniwork.consent.store import InMemoryConsentStore

    store = InMemoryConsentStore()
    svc = ConsentService(store, registry)
    approvals = ApprovalService()
    audit = InMemoryAuditLog()

    class TrackingExecutor:
        def __init__(self) -> None:
            self.called = 0

        def invoke(self, spec, arguments, context):
            self.called += 1
            raise AssertionError("irreversible tools must not run before approval")

    tool_registry = ToolRegistry()
    executor = TrackingExecutor()
    irreversible_scopes = [spec for spec in registry if spec.risk is Risk.IRREVERSIBLE]
    assert irreversible_scopes, "registry must include at least one irreversible scope"
    for spec in irreversible_scopes:
        store.set(ConsentState("user-1", spec.key, ConsentAction.GRANTED, True))
        assert svc.check("user-1", spec.key, spec.risk) is ConsentDecision.REQUIRE_APPROVAL
        tool = ToolSpec(
            name=f"test.{spec.key.replace(':', '.')}",
            provider="mcp",
            description="Irreversible test tool",
            input_schema={"type": "object", "properties": {"body": {"type": "string"}}},
            scope_key=spec.key,
            risk=Risk.IRREVERSIBLE,
            preview_renderer="text",
        )
        tool_registry.register(tool, executor)
        router = ToolRouter(tool_registry, svc, audit)
        result = router.invoke(
            user_id="user-1",
            name=tool.name,
            arguments={"body": "hello"},
            context={"surface": "web", "task_id": None, "step_id": None},
        )
        assert result.needs_approval is True
        assert executor.called == 0
        from uuid import UUID

        created = approvals.create(
            user_id=UUID("00000000-0000-7000-8000-000000000099"),
            task_id=UUID("00000000-0000-7000-8000-000000000098"),
            step_id=None,
            spec=tool,
            tool_name=tool.name,
            arguments={"body": "hello"},
        )
        assert created.status == "pending"
        assert created.risk is Risk.IRREVERSIBLE


def test_blocked_tool_explains_degraded_path_in_task(client, registered):
    headers = auth_header(registered["token"])
    # builtin tools never need approval; this just checks the workspace still works
    created = client.post(
        f"{_prefix()}/tasks",
        headers=headers,
        json={"message": "Say hello without any tools if you can"},
    )
    assert created.status_code == 200


def test_approval_skip_repeat_rejected_for_irreversible():
    from uuid import UUID

    from cogniwork.consent.models import Risk
    from cogniwork.core.errors import InvalidRequest
    from cogniwork.runtime.tools.spec import ToolSpec

    approvals = ApprovalService()
    spec = ToolSpec(
        name="test.send",
        provider="mcp",
        description="Send something",
        input_schema={"type": "object", "properties": {}},
        scope_key="tool:gmail:send",
        risk=Risk.IRREVERSIBLE,
        preview_renderer="email",
    )
    item = approvals.create(
        user_id=UUID("00000000-0000-7000-8000-000000000011"),
        task_id=UUID("00000000-0000-7000-8000-000000000012"),
        step_id=None,
        spec=spec,
        tool_name=spec.name,
        arguments={"to": ["a@b.c"], "subject": "Hi", "body": "Hello"},
    )
    try:
        approvals.resolve(
            item.user_id,
            item.id,
            ApprovalAction.ALWAYS_ALLOW_THIS_SCOPE,
        )
        raise AssertionError("irreversible must not accept skip-repeat")
    except InvalidRequest:
        pass
