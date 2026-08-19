"""Drive a Skill workflow through the shared Runtime (P0-06 §5.3 / M3).

Nesting is limited to one level and the limit is enforced here, not only
in docs (B8). Other features must not depend on nesting — it is the third
cut in the A9.1 trigger plan.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from cogniwork.core.clock import now
from cogniwork.core.errors import InvalidRequest
from cogniwork.core.ids import new_id
from cogniwork.runtime.llm.router import RoutingRequest
from cogniwork.runtime.llm.types import ChatMessage
from cogniwork.runtime.models import StepStatus, StepType, TaskStatus
from cogniwork.skill.workflow import MAX_NESTING
from cogniwork.tools.catalog import load_catalog


class SkillCursor:
    def __init__(self, skill: dict[str, Any], *, depth: int = 0) -> None:
        self.stack: list[tuple[dict[str, Any], int, int]] = [(skill, 0, depth)]
        self.outputs: dict[str, str] = {}

    @property
    def current(self) -> tuple[dict[str, Any], int, int] | None:
        return self.stack[-1] if self.stack else None

    def step(self) -> dict[str, Any] | None:
        frame = self.current
        if frame is None:
            return None
        skill, index, _depth = frame
        workflow = skill.get("workflow") or []
        if index >= len(workflow):
            return None
        return workflow[index]

    def advance(self) -> None:
        if not self.stack:
            return
        skill, index, depth = self.stack[-1]
        self.stack[-1] = (skill, index + 1, depth)
        while self.stack:
            skill, index, depth = self.stack[-1]
            if index < len(skill.get("workflow") or []):
                return
            self.stack.pop()

    def push_nested(self, nested: dict[str, Any], depth: int) -> None:
        if depth > MAX_NESTING:
            raise InvalidRequest(
                "Skill nesting is limited to one level. This skill tried to call another skill.",
                details={"nesting_depth": depth},
            )
        self.stack.append((nested, 0, depth))


def load_cursor(runtime: Any, task: Any) -> SkillCursor | None:
    skill_id = task.skill_id or (task.input or {}).get("skill_id")
    if not skill_id:
        return None
    existing = getattr(runtime, "skill_cursors", {}).get(str(task.id))
    if existing is not None:
        return existing
    skills = getattr(runtime, "skills", None)
    if skills is None:
        return None
    payload = skills.get(task.user_id, UUID(str(skill_id)))
    skill = payload.get("skill") if "skill" in payload else payload
    cursor = SkillCursor(skill, depth=int((task.input or {}).get("nesting_depth") or 0))
    runtime.skill_cursors[str(task.id)] = cursor
    return cursor


def drive_skill_act(runtime: Any, state: dict[str, Any]) -> dict[str, Any] | None:
    """Return a graph state if this task is skill-driven; None to use the free loop."""
    from cogniwork.runtime.graph import _open_step, _run_tool, _set_status

    task = runtime.store.get_task(UUID(state["user_id"]), UUID(state["task_id"]))
    if task is None:
        return {**state, "failed": True}
    cursor = load_cursor(runtime, task)
    if cursor is None:
        return None
    iteration = int(state.get("iteration") or 0) + 1
    if iteration > runtime.step_limit:
        task.error = {
            "code": "budget_exceeded",
            "message": f"Stopped after {runtime.step_limit} steps.",
            "retryable": True,
        }
        runtime.store.save_task(task)
        return {**state, "iteration": iteration, "failed": True}
    step = cursor.step()
    if step is None:
        return {**state, "done": True}

    dry_run = bool((task.input or {}).get("dry_run"))
    inputs = dict((task.input or {}).get("skill_inputs") or {})
    step_type = step.get("type")

    try:
        if step_type == "skill":
            _enter_nested(runtime, task, cursor, step)
            return {**state, "iteration": iteration, "done": False}
        if step_type == "collect_input":
            _run_collect(runtime, task, step, inputs)
        elif step_type == "llm":
            _run_llm_step(runtime, task, step, inputs)
        elif step_type == "tool":
            paused = _run_tool_step(runtime, task, step, inputs, dry_run, iteration, _run_tool)
            if paused:
                return {**state, "iteration": iteration, "paused": True}
        elif step_type == "approval":
            paused = _run_approval_step(runtime, task, step, cursor, _open_step, _set_status)
            if paused:
                return {**state, "iteration": iteration, "paused": True}
        else:
            raise InvalidRequest("Unknown skill step type.", details={"type": step_type})
    except InvalidRequest as exc:
        task.error = {"code": "invalid_input", "message": exc.message, "retryable": False}
        runtime.store.save_task(task)
        return {**state, "iteration": iteration, "failed": True}
    except Exception as exc:
        task.error = {
            "code": "internal_error",
            "message": "This skill step failed.",
            "retryable": True,
            "detail": type(exc).__name__,
        }
        runtime.store.save_task(task)
        return {**state, "iteration": iteration, "failed": True}

    cursor.advance()
    if cursor.step() is None:
        return {**state, "iteration": iteration, "done": True}
    return {**state, "iteration": iteration, "done": False}


def _enter_nested(runtime: Any, task: Any, cursor: SkillCursor, step: dict[str, Any]) -> None:
    frame = cursor.current
    depth = (frame[2] if frame else 0) + 1
    if depth > MAX_NESTING:
        raise InvalidRequest(
            "Skill nesting is limited to one level. This skill tried to call another skill.",
            details={"step_id": step.get("id"), "nesting_depth": depth},
        )
    nested_id = step.get("skill_id")
    payload = runtime.skills.get(task.user_id, UUID(str(nested_id)))
    if isinstance(payload, dict) and "skill" in payload:
        nested = payload.get("skill")
    else:
        nested = payload
    # Consume the parent skill-call step first. Otherwise the nested workflow
    # finishes, the parent frame is still on this step, and we enter it again.
    cursor.advance()
    cursor.push_nested(nested, depth)


def _run_collect(runtime: Any, task: Any, step: dict[str, Any], inputs: dict[str, Any]) -> None:
    from cogniwork.runtime.graph import _finish_step, _open_step

    opened = _open_step(
        runtime,
        task,
        StepType.LLM,
        step["title"],
        None,
        {"fields": step.get("fields")},
    )
    missing = [key for key in (step.get("fields") or []) if key not in inputs]
    started = now()
    _finish_step(
        runtime,
        opened,
        StepStatus.SUCCEEDED if not missing else StepStatus.SKIPPED,
        {"fields": step.get("fields")},
        {"present": sorted(inputs), "missing": missing},
        started,
    )


def _run_llm_step(runtime: Any, task: Any, step: dict[str, Any], inputs: dict[str, Any]) -> None:
    from cogniwork.runtime.graph import _finish_step, _open_step

    opened = _open_step(runtime, task, StepType.LLM, step["title"], None, None)
    started = now()
    client = runtime.router.client_for(
        RoutingRequest(
            task_intent=task.intent,
            context_tokens=0,
            needs_vision=False,
            needs_tool_use=False,
            latency_class="interactive",
            cost_tier="standard",
        )
    )
    instruction = step.get("instruction") or step["title"]
    messages = [
        ChatMessage("system", "Follow this skill step. Do not invent facts."),
        ChatMessage("user", f"{instruction}\nInputs: {json.dumps(inputs, default=str)}"),
    ]
    result = client.complete(
        messages,
        [],
        on_delta=lambda chunk: runtime.events.publish(str(task.id), "message.delta", text=chunk),
    )
    runtime.messages.setdefault(str(task.id), []).append(
        ChatMessage("assistant", result.text or instruction)
    )
    _finish_step(
        runtime,
        opened,
        StepStatus.SUCCEEDED,
        None,
        {"has_text": bool(result.text)},
        started,
    )
    cursor = runtime.skill_cursors[str(task.id)]
    cursor.outputs[step["id"]] = result.text or ""
    task.token_in += result.token_in
    task.token_out += result.token_out
    runtime.store.save_task(task)


def _run_tool_step(
    runtime: Any,
    task: Any,
    step: dict[str, Any],
    inputs: dict[str, Any],
    dry_run: bool,
    iteration: int,
    run_tool: Any,
) -> bool:
    from cogniwork.runtime.graph import _finish_step, _open_step

    name = step.get("tool")
    if not name:
        opened = _open_step(runtime, task, StepType.TOOL, step["title"], None, None)
        started = now()
        _finish_step(
            runtime,
            opened,
            StepStatus.SKIPPED,
            None,
            {"reason": "tool_unset"},
            started,
            {"message": "This step has no tool yet. Pick one in the editor."},
        )
        return False
    catalog = load_catalog().tool(name)
    risk = catalog.risk.value if catalog else "read"
    arguments = dict(step.get("args_hint") or {})
    for key, value in list(arguments.items()):
        if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
            arguments[key] = inputs.get(value[2:-2].strip(), value)
    if dry_run and risk in {"write", "irreversible"}:
        opened = _open_step(
            runtime,
            task,
            StepType.TOOL,
            step["title"],
            catalog.scope_key if catalog else None,
            {"dry_run": True, "tool": name},
        )
        started = now()
        preview = f"Would call {name} with {sorted(arguments)}."
        runtime.events.publish(str(task.id), "message.delta", text=preview + "\n")
        _finish_step(
            runtime,
            opened,
            StepStatus.SUCCEEDED,
            {"dry_run": True},
            {"preview": True, "tool": name, "risk": risk},
            started,
        )
        runtime.skill_cursors[str(task.id)].outputs[step["id"]] = preview
        return False
    call_id = str(new_id())
    return bool(run_tool(runtime, task, call_id, name, arguments, iteration))


def _run_approval_step(
    runtime: Any,
    task: Any,
    step: dict[str, Any],
    cursor: SkillCursor,
    open_step: Any,
    set_status: Any,
) -> bool:
    from cogniwork.consent.models import Risk
    from cogniwork.runtime.approvals import PendingToolCall
    from cogniwork.runtime.tools.spec import ToolSpec

    preview = cursor.outputs.get(step.get("preview_from") or "", "")
    spec = ToolSpec(
        name="skill.approval",
        provider="builtin",
        description="Skill approval gate",
        input_schema={"type": "object"},
        scope_key=None,
        risk=Risk.WRITE,
        preview_renderer="text",
    )
    opened = open_step(runtime, task, StepType.APPROVAL, step["title"], None, None)
    approval = runtime.approvals.create(
        user_id=task.user_id,
        task_id=task.id,
        step_id=opened.id,
        spec=spec,
        tool_name="skill.approval",
        arguments={"preview": preview[:2000]},
    )
    runtime.pending_calls[str(task.id)] = PendingToolCall(
        task_id=task.id,
        user_id=task.user_id,
        tool_name="skill.approval",
        arguments={"preview": preview[:2000]},
        call_id=str(opened.id),
        iteration=0,
        step_id=opened.id,
        approval_id=approval.id,
    )
    opened.status = StepStatus.PENDING
    runtime.store.save_step(opened)
    set_status(runtime, task, TaskStatus.WAITING_APPROVAL)
    runtime.events.publish(str(task.id), "task.status", status=task.status.value)
    runtime.events.publish(
        str(task.id),
        "approval.requested",
        approval_id=str(approval.id),
        title=approval.title,
        risk=approval.risk.value,
        scope=approval.scope_key,
        preview=approval.preview,
    )
    return True
