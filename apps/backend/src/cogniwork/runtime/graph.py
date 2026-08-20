"""LangGraph 执行图：prepare → act → observe → finalize（P0-03 §4）。

业务代码不要直接依赖本模块，走 TaskEngine 门面。
框架若不合用，换实现时上层（API / 工作台）不用改。
"""

from __future__ import annotations

import json
from typing import Any, Literal, TypedDict
from uuid import UUID

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from cogniwork.core.clock import now
from cogniwork.core.ids import new_id
from cogniwork.runtime.approvals import PendingToolCall
from cogniwork.runtime.digest import digest_args
from cogniwork.runtime.llm.router import RoutingRequest
from cogniwork.runtime.llm.types import ChatMessage
from cogniwork.runtime.models import (
    StepStatus,
    StepType,
    TaskStatus,
    TaskStep,
    can_transition,
)
from cogniwork.runtime.tools.spec import ToolSpec


class GraphState(TypedDict):
    task_id: str
    user_id: str
    iteration: int
    done: bool
    failed: bool
    cancel: bool
    paused: bool


def compile_graph(runtime: Any) -> Any:
    graph = StateGraph(GraphState)
    graph.add_node("prepare", lambda state: _prepare(runtime, state))
    graph.add_node("act", lambda state: _act(runtime, state))
    graph.add_node("observe", lambda state: _observe(runtime, state))
    graph.add_node("finalize", lambda state: _finalize(runtime, state))
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "act")
    graph.add_conditional_edges(
        "act",
        _after_act,
        {"observe": "observe", "finalize": "finalize", "pause": END},
    )
    graph.add_conditional_edges(
        "observe",
        _after_observe,
        {"act": "act", "finalize": "finalize"},
    )
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=MemorySaver())


def _after_act(state: GraphState) -> Literal["observe", "finalize", "pause"]:
    if state.get("paused"):
        return "pause"
    if state.get("done") or state.get("failed") or state.get("cancel"):
        return "finalize"
    return "observe"


def _after_observe(state: GraphState) -> Literal["act", "finalize"]:
    if state.get("done") or state.get("failed") or state.get("cancel"):
        return "finalize"
    return "act"


def _prepare(runtime: Any, state: GraphState) -> GraphState:
    task = runtime.store.get_task(UUID(state["user_id"]), UUID(state["task_id"]))
    if task is None:
        return {**state, "failed": True}
    _set_status(runtime, task, TaskStatus.RUNNING)
    if task.started_at is None:
        task.started_at = now()
        runtime.store.save_task(task)
    runtime.events.publish(str(task.id), "task.status", status=task.status.value)
    files = task.input.get("file_ids") or []
    names = []
    for file_id in files:
        uploaded = runtime.store.get_file(task.user_id, UUID(str(file_id)))
        if uploaded:
            names.append(f"{uploaded.filename} ({uploaded.id})")
    memory_xml = ""
    profile_xml = ""
    used = []
    memory = getattr(runtime, "memory", None)
    if memory is not None:
        try:
            query = str(task.input.get("message") or "")
            bundle = memory.retrieve(task.user_id, query)
            memory_xml = bundle.xml
            used = [
                {
                    "id": str(row.item.id),
                    "type": row.item.type.value,
                    "summary": row.item.summary,
                    "content": row.item.content,
                    "source_ref": row.item.source_ref,
                    "score": round(row.score, 3),
                }
                for row in bundle.preferences + bundle.facts + bundle.past
            ]
            runtime.used_memories[str(task.id)] = used
        except Exception:
            runtime.used_memories[str(task.id)] = []
    profile = getattr(runtime, "profile", None)
    if profile is not None:
        try:
            profile_xml = profile.render_card(task.user_id)
        except Exception:
            profile_xml = ""
    runtime.messages[str(task.id)] = [
        ChatMessage(
            "system",
            _system_prompt(json.dumps(files), names, memory_xml, profile_xml),
        ),
        ChatMessage("user", str(task.input.get("message") or "")),
    ]
    return {**state, "done": False, "failed": False, "paused": False}


def _act(runtime: Any, state: GraphState) -> GraphState:
    if runtime.is_cancelled(state["task_id"]):
        return {**state, "cancel": True}
    task = runtime.store.get_task(UUID(state["user_id"]), UUID(state["task_id"]))
    if task is None:
        return {**state, "failed": True}
    if _timed_out(task):
        task.error = {
            "code": "internal_error",
            "message": "This task ran longer than 30 minutes, so I stopped.",
            "retryable": True,
        }
        runtime.store.save_task(task)
        return {**state, "failed": True, "timed_out": True}
    from cogniwork.runtime.skill_driver import drive_skill_act

    driven = drive_skill_act(runtime, state)
    if driven is not None:
        return driven
    iteration = int(state.get("iteration") or 0) + 1
    if iteration > runtime.step_limit:
        task.error = {
            "code": "budget_exceeded",
            "message": f"Stopped after {runtime.step_limit} steps.",
            "retryable": True,
        }
        runtime.store.save_task(task)
        return {**state, "iteration": iteration, "failed": True}

    specs = _available_specs(runtime)
    cost_tier = "economy" if _daily_capped(runtime, task) else "standard"
    client = runtime.router.client_for(
        RoutingRequest(
            task_intent=task.intent,
            context_tokens=0,
            needs_vision=False,
            needs_tool_use=True,
            latency_class="interactive",
            cost_tier=cost_tier,
        ),
        user_id=str(task.user_id),
    )
    step = _open_step(
        runtime,
        task,
        StepType.LLM,
        "Thinking through the next step",
        None,
        None,
    )
    runtime.events.publish(
        str(task.id),
        "step.started",
        step_id=str(step.id),
        type=step.type.value,
        title=step.title,
    )
    started = now()

    def on_delta(chunk: str) -> None:
        runtime.events.publish(str(task.id), "message.delta", text=chunk)

    try:
        result = client.complete(
            runtime.messages[str(task.id)],
            [_tool_schema(spec) for spec in specs],
            on_delta=on_delta,
        )
    except Exception as exc:
        _finish_step(
            runtime, step, StepStatus.FAILED, None, {"message": type(exc).__name__}, started
        )
        task.error = {
            "code": "upstream_error",
            "message": "The language model did not respond.",
            "retryable": True,
            "step_id": str(step.id),
        }
        runtime.store.save_task(task)
        return {**state, "iteration": iteration, "failed": True}

    task.token_in += result.token_in
    task.token_out += result.token_out
    from cogniwork.runtime.governance import cost_for_tokens, record_usage, should_pause_for_cost

    added = cost_for_tokens(result.token_in, result.token_out)
    task.cost_usd = float(task.cost_usd or 0) + added
    skills = getattr(runtime, "skills", None)
    if skills is not None:
        record_usage(skills.store, task.user_id, added, result.token_in, result.token_out)
    runtime.store.save_task(task)
    if should_pause_for_cost(task, runtime.settings):
        task.error = {
            "code": "budget_exceeded",
            "message": f"This task has spent ${float(task.cost_usd):.2f}. Continue?",
            "retryable": True,
        }
        runtime.store.save_task(task)
        return {**state, "iteration": iteration, "failed": True}
    _finish_step(
        runtime,
        step,
        StepStatus.SUCCEEDED,
        {"vendor": result.vendor, "model": result.model},
        {"tool_calls": len(result.tool_calls), "has_text": bool(result.text)},
        started,
    )

    if result.text and not result.tool_calls:
        runtime.messages[str(task.id)].append(ChatMessage("assistant", result.text))
        return {**state, "iteration": iteration, "done": True}

    if not result.tool_calls:
        return {**state, "iteration": iteration, "done": True}

    assistant_bits = result.text or ""
    runtime.messages[str(task.id)].append(
        ChatMessage("assistant", assistant_bits or json.dumps([c.name for c in result.tool_calls]))
    )

    for call in result.tool_calls:
        if runtime.is_cancelled(state["task_id"]):
            return {**state, "iteration": iteration, "cancel": True}
        if _run_tool(runtime, task, call.id, call.name, call.arguments, iteration):
            return {**state, "iteration": iteration, "paused": True}

    artifacts = runtime.store.list_artifacts(task.user_id, task.id)
    # stub / 周报路径：写出产物后即可结束，避免空转。
    if artifacts and iteration >= 2:
        if not result.text:
            wrap = (
                "Done. I turned the spreadsheet into a weekly report. "
                "Download it from the artifacts panel."
            )
            runtime.events.publish(str(task.id), "message.delta", text=wrap)
            runtime.messages[str(task.id)].append(ChatMessage("assistant", wrap))
        return {**state, "iteration": iteration, "done": True}

    return {**state, "iteration": iteration, "done": False}


def _observe(runtime: Any, state: GraphState) -> GraphState:
    if runtime.is_cancelled(state["task_id"]):
        return {**state, "cancel": True}
    task = runtime.store.get_task(UUID(state["user_id"]), UUID(state["task_id"]))
    if task is None:
        return {**state, "failed": True}
    repeats = _repeated_tool_calls(runtime.messages.get(str(task.id), []))
    if repeats >= 3:
        task.error = {
            "code": "internal_error",
            "message": "The same step repeated without progress, so I stopped.",
            "retryable": True,
        }
        runtime.store.save_task(task)
        return {**state, "failed": True}
    return state


def _finalize(runtime: Any, state: GraphState) -> GraphState:
    task = runtime.store.get_task(UUID(state["user_id"]), UUID(state["task_id"]))
    if task is None:
        return state
    artifacts = runtime.store.list_artifacts(task.user_id, task.id)
    if state.get("cancel"):
        _set_status(runtime, task, TaskStatus.CANCELLED)
        terminal = "cancelled"
    elif state.get("failed"):
        from cogniwork.runtime.governance import finalize_result

        summary = (task.error or {}).get("message") or _last_assistant_text(
            runtime.messages.get(str(task.id), [])
        )
        task.result = finalize_result(task, summary, artifacts)
        _set_status(runtime, task, TaskStatus.FAILED)
        terminal = "failed"
    elif state.get("timed_out"):
        _set_status(runtime, task, TaskStatus.TIMED_OUT)
        terminal = "timed_out"
    else:
        from cogniwork.runtime.governance import finalize_result

        summary = _last_assistant_text(runtime.messages.get(str(task.id), []))
        task.result = finalize_result(task, summary, artifacts)
        if task.result.get("failed_steps"):
            leftover = "; ".join(task.result.get("failed_steps") or [])
            task.result["summary"] = (
                f"{summary}\n\nI did not finish everything. Not done: {leftover}."
            ).strip()
        _set_status(runtime, task, TaskStatus.SUCCEEDED)
        terminal = "succeeded"
    task.ended_at = now()
    runtime.store.save_task(task)
    memory = getattr(runtime, "memory", None)
    if memory is not None:
        try:
            memory.record_episode(task)
            from cogniwork.memory.extract import extract_from_task

            candidates = extract_from_task(memory, task)
            for item in candidates:
                runtime.events.publish(
                    str(task.id),
                    "memory.candidate",
                    memory_id=str(item.id),
                    summary=item.summary,
                    type=item.type.value,
                    status=item.status.value,
                )
        except Exception:
            logger = __import__("logging").getLogger("cogniwork.runtime")
            logger.exception("memory finalize failed for %s", task.id)
    profile = getattr(runtime, "profile", None)
    if profile is not None and terminal == "succeeded":
        try:
            from cogniwork.profile.extract import drafts_from_task

            for item in profile.propose(task.user_id, drafts_from_task(task)):
                runtime.events.publish(
                    str(task.id),
                    "memory.candidate",
                    memory_id=str(item.id),
                    summary=item.key,
                    type="profile",
                    status=item.status.value,
                )
        except Exception:
            logger = __import__("logging").getLogger("cogniwork.runtime")
            logger.exception("profile finalize failed for %s", task.id)
    runtime.events.publish(str(task.id), "task.status", status=task.status.value)
    runtime.events.publish(
        str(task.id),
        "task.finished",
        status=terminal,
        artifact_ids=[str(a.id) for a in artifacts],
    )
    runtime.events.close(str(task.id))
    _record_skill_run(runtime, task, terminal)
    return state


def _run_tool(
    runtime: Any,
    task: Any,
    call_id: str,
    name: str,
    arguments: dict[str, Any],
    iteration: int = 0,
) -> bool:
    spec = runtime.tool_router.resolve(name)
    title = _tool_title(spec, name)
    step = _open_step(
        runtime,
        task,
        StepType.TOOL,
        title,
        spec.scope_key if spec else None,
        digest_args(arguments),
    )
    runtime.events.publish(
        str(task.id),
        "step.started",
        step_id=str(step.id),
        type=step.type.value,
        title=title,
    )
    runtime.events.publish(
        str(task.id),
        "tool.call",
        name=name,
        args_digest=digest_args(arguments),
    )
    started = now()
    result = runtime.tool_router.invoke(
        user_id=str(task.user_id),
        name=name,
        arguments=arguments,
        context={
            "store": runtime.store,
            "user_id": str(task.user_id),
            "task_id": str(task.id),
            "step_id": str(step.id),
            "surface": task.surface.value,
            "file_ids": task.input.get("file_ids") or [],
            "memory": getattr(runtime, "memory", None),
            "dry_run": bool((task.input or {}).get("dry_run")),
        },
    )
    if result.needs_approval:
        approval = runtime.approvals.create(
            user_id=task.user_id,
            task_id=task.id,
            step_id=step.id,
            spec=spec,
            tool_name=name,
            arguments=arguments,
        )
        runtime.pending_calls[str(task.id)] = PendingToolCall(
            task_id=task.id,
            user_id=task.user_id,
            tool_name=name,
            arguments=arguments,
            call_id=call_id,
            iteration=iteration,
            step_id=step.id,
            approval_id=approval.id,
        )
        step.status = StepStatus.PENDING
        runtime.store.save_step(step)
        _set_status(runtime, task, TaskStatus.WAITING_APPROVAL)
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
    if result.blocked:
        scope_key = (result.data or {}).get("scope_key") or (spec.scope_key if spec else None)
        if scope_key:
            runtime.blocked_scopes[str(task.id)] = str(scope_key)
    status = StepStatus.SUCCEEDED if result.ok else StepStatus.FAILED
    _finish_step(
        runtime,
        step,
        status,
        digest_args(arguments),
        {"ok": result.ok, "blocked": result.blocked, "keys": sorted((result.data or {}).keys())},
        started,
        None if result.ok else {"message": result.content},
    )
    runtime.events.publish(
        str(task.id),
        "tool.result",
        name=name,
        ok=result.ok,
        blocked=result.blocked,
        scope_key=(result.data or {}).get("scope_key") or (spec.scope_key if spec else None),
    )
    for item in (result.data or {}).get("artifacts") or []:
        runtime.events.publish(
            str(task.id),
            "artifact.created",
            artifact_id=item.get("id"),
            filename=item.get("filename"),
            content_type=item.get("content_type"),
            size_bytes=item.get("size_bytes"),
        )
    runtime.messages[str(task.id)].append(
        ChatMessage("tool", result.content, tool_call_id=call_id, name=name)
    )
    return False


def _open_step(
    runtime: Any,
    task: Any,
    step_type: StepType,
    title: str,
    scope_key: str | None,
    digest: dict | None,
) -> TaskStep:
    seq = len(task.steps) + 1
    step = TaskStep(
        id=new_id(),
        task_id=task.id,
        seq=seq,
        type=step_type,
        title=title,
        status=StepStatus.RUNNING,
        scope_key=scope_key,
        input_digest=digest,
        output_digest=None,
        error=None,
        duration_ms=None,
        created_at=now(),
    )
    runtime.store.add_step(step)
    if all(existing.id != step.id for existing in task.steps):
        task.steps.append(step)
    return step


def _finish_step(
    runtime: Any,
    step: TaskStep,
    status: StepStatus,
    input_digest: dict | None,
    output_digest: dict | None,
    started,
    error: dict | None = None,
) -> None:
    step.status = status
    if input_digest is not None:
        step.input_digest = input_digest
    step.output_digest = output_digest
    step.error = error
    step.duration_ms = int((now() - started).total_seconds() * 1000)
    runtime.store.save_step(step)
    runtime.events.publish(
        str(step.task_id),
        "step.finished",
        step_id=str(step.id),
        status=status.value,
        title=step.title,
        duration_ms=step.duration_ms,
    )


def _set_status(runtime: Any, task: Any, target: TaskStatus) -> None:
    if task.status is target:
        return
    if not can_transition(task.status, target):
        task.status = target
    else:
        task.status = target
    task.updated_at = now()
    runtime.store.save_task(task)


def _system_prompt(
    file_ids_json: str, names: list[str], memory_xml: str = "", profile_xml: str = ""
) -> str:
    listing = ", ".join(names) if names else "none"
    memory_block = f"\n{memory_xml}\n" if memory_xml else "\n"
    profile_block = f"\n{profile_xml}\n" if profile_xml else ""
    return (
        "You are CogniWork, an AI coworker. Complete the user's task with the tools "
        "you have. Read uploaded files before writing artifacts. Do not claim you used "
        "a tool you do not have. Prefer builtin.write_artifact with "
        "generate=weekly_report when the user wants a weekly report from a spreadsheet."
        f"{profile_block}{memory_block}"
        "When a user profile is present, match its tone and tools. "
        "When memory is present, use it and mention the source. "
        "Do not invent memories or profile facts that are not listed.\n"
        f"file_ids={file_ids_json}\n"
        f"uploaded={listing}\n"
    )


def _tool_schema(spec: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.input_schema,
        },
    }


def _tool_title(spec: ToolSpec | None, name: str) -> str:
    if spec is None:
        return name
    if name.endswith("read_uploaded_file"):
        return "Reading the uploaded file"
    if name.endswith("write_artifact"):
        return "Writing the deliverable"
    if name.endswith("search_memory"):
        return "Searching your memory"
    if name.endswith("ask_user"):
        return "Asking a clarifying question"
    return spec.description.split(".")[0]


def _last_assistant_text(messages: list[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.role == "assistant" and message.content.strip():
            return message.content.strip()
    return "Task finished."


def _repeated_tool_calls(messages: list[ChatMessage]) -> int:
    names = [m.name for m in messages if m.role == "tool" and m.name]
    if len(names) < 3:
        return 0
    if names[-1] == names[-2] == names[-3]:
        return 3
    return 0


def _timed_out(task: Any) -> bool:
    started = task.started_at
    if started is None:
        return False
    return (now() - started).total_seconds() > 30 * 60


def _daily_capped(runtime: Any, task: Any) -> bool:
    from cogniwork.runtime.governance import daily_over_cap

    skills = getattr(runtime, "skills", None)
    if skills is None:
        return False
    return daily_over_cap(skills.store, task.user_id, runtime.settings)


def _available_specs(runtime: Any) -> list[ToolSpec]:
    specs = runtime.tools.specs()
    resilience = getattr(runtime.tool_router, "resilience", None)
    if resilience is None:
        return specs
    open_providers = resilience.open_providers()
    if not open_providers:
        return specs
    kept = []
    for spec in specs:
        provider = spec.name.split(".", 1)[0] if spec.provider == "mcp" else spec.provider
        if provider in open_providers:
            continue
        kept.append(spec)
    return kept


def _record_skill_run(runtime: Any, task: Any, terminal: str) -> None:
    skill_id = task.skill_id or (task.input or {}).get("skill_id")
    skills = getattr(runtime, "skills", None)
    if not skill_id or skills is None:
        return
    try:
        skills.mark_run(task.user_id, UUID(str(skill_id)), success=terminal == "succeeded")
    except Exception:
        return
    if terminal == "succeeded":
        for step in task.steps:
            if step.scope_key:
                skills.record_event(
                    task.user_id,
                    "scope_executed",
                    {"scope": step.scope_key, "ok": True, "task_id": str(task.id)},
                )
