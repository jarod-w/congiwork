"""Skills: CRUD, presets, draft, dry-run, nesting, exit-criteria (P0-06)."""

from __future__ import annotations

from uuid import UUID

from cogniwork.core.config import get_settings
from cogniwork.skill.presets import load_presets
from cogniwork.skill.workflow import MAX_NESTING

from .conftest import auth_header


def _prefix() -> str:
    return get_settings().api_prefix


def _save(client, headers, body: dict) -> dict:
    response = client.post(f"{_prefix()}/skills", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()["skill"]


def test_presets_have_four_zero_auth_and_no_connector_names():
    presets = load_presets()
    assert len(presets) == 5
    zero = [item for item in presets if not item["required_scopes"]]
    assert len(zero) == 4
    blob = str(presets).lower()
    for name in ("gmail", "slack", "notion", "github", "hubspot"):
        assert name not in blob
    send = next(item for item in presets if item["id"] == "quarterly-channel-review")
    last = send["workflow"][-1]
    assert last["type"] == "tool"
    assert last.get("tool") is None
    assert last.get("needs_clarification") is True


def test_skill_crud_and_version_snapshot(client, registered):
    headers = auth_header(registered["token"])
    created = _save(
        client,
        headers,
        {
            "name": "Weekly wrap",
            "description": "Turn a sheet into a weekly wrap",
            "workflow": [
                {
                    "id": "s1",
                    "type": "collect_input",
                    "title": "Confirm the period",
                    "fields": ["period"],
                },
                {
                    "id": "s2",
                    "type": "llm",
                    "title": "Write the wrap",
                    "instruction": "Summarize the uploaded table.",
                },
            ],
        },
    )
    assert created["version"] == 1
    assert created["required_scopes"] == []
    patched = client.patch(
        f"{_prefix()}/skills/{created['id']}",
        headers=headers,
        json={"description": "Updated wrap", "change_note": "tweak copy"},
    )
    assert patched.status_code == 200
    assert patched.json()["skill"]["version"] == 2
    versions = client.get(f"{_prefix()}/skills/{created['id']}/versions", headers=headers)
    assert versions.status_code == 200
    assert len(versions.json()["versions"]) == 2


def test_required_scopes_derived_from_workflow(client, registered):
    headers = auth_header(registered["token"])
    skill = _save(
        client,
        headers,
        {
            "name": "Issue opener",
            "description": "Open a tracking issue",
            "workflow": [
                {
                    "id": "s1",
                    "type": "tool",
                    "title": "Open the tracking issue",
                    "tool": "github.create_issue",
                    "on_error": "ask_user",
                }
            ],
        },
    )
    assert skill["required_scopes"] == ["tool:github:write"]
    assert skill["tools"] == ["github.create_issue"]


def test_cannot_activate_with_clarification(client, registered):
    headers = auth_header(registered["token"])
    copied = client.post(
        f"{_prefix()}/skills/draft",
        headers=headers,
        json={"preset_id": "quarterly-channel-review"},
    )
    assert copied.status_code == 200
    skill_id = copied.json()["skill"]["id"]
    assert copied.json()["skill"]["source"] == "preset_copy"
    failed = client.patch(
        f"{_prefix()}/skills/{skill_id}",
        headers=headers,
        json={"status": "active"},
    )
    assert failed.status_code == 400


def test_natural_language_draft_and_unset_tool(client, registered):
    headers = auth_header(registered["token"])
    drafted = client.post(
        f"{_prefix()}/skills/draft",
        headers=headers,
        json={
            "description": (
                "Each quarter pull channel numbers, make a table, "
                "then send it to the people who need it."
            )
        },
    )
    assert drafted.status_code == 200
    draft = drafted.json()["draft"]
    assert draft["status"] == "draft"
    send_steps = [step for step in draft["workflow"] if "send" in step["title"].lower()]
    assert send_steps
    assert send_steps[-1].get("tool") in {None, ""} or send_steps[-1].get("needs_clarification")


def test_keyword_suggest_does_not_auto_run(client, registered):
    headers = auth_header(registered["token"])
    skill = _save(
        client,
        headers,
        {
            "name": "Channel review",
            "description": "Quarterly channel review",
            "trigger": {"type": "keyword", "patterns": ["quarterly review"]},
            "status": "active",
            "workflow": [
                {"id": "s1", "type": "llm", "title": "Draft the review", "instruction": "Write it."}
            ],
        },
    )
    suggested = client.post(
        f"{_prefix()}/skills/suggest",
        headers=headers,
        json={"text": "Can you do the quarterly review?"},
    )
    assert suggested.status_code == 200
    ids = [item["id"] for item in suggested.json()["skills"]]
    assert skill["id"] in ids


def test_copy_preset_excluded_from_exit_criteria(client, registered):
    headers = auth_header(registered["token"])
    for _ in range(3):
        client.post(
            f"{_prefix()}/skills/draft",
            headers=headers,
            json={"preset_id": "channel-weekly"},
        )
    metrics = client.get(f"{_prefix()}/events/exit-criteria", headers=headers)
    assert metrics.status_code == 200
    organic = metrics.json()["organic_skills"]
    assert organic["organic_created"] == 0
    assert organic["qualifies"] is False


def test_dry_run_does_not_call_write_tools(client, registered):
    headers = auth_header(registered["token"])
    from cogniwork.main import app

    transport = app.state.mcp_executor._client.transport
    before = len(getattr(transport, "calls", []))
    skill = _save(
        client,
        headers,
        {
            "name": "Send later",
            "description": "Would send if this were real",
            "status": "active",
            "workflow": [
                {
                    "id": "s1",
                    "type": "llm",
                    "title": "Draft the note",
                    "instruction": "Write a short note.",
                },
                {
                    "id": "s2",
                    "type": "tool",
                    "title": "Send it",
                    "tool": "gmail.send_message",
                    "args_hint": {"to": ["a@example.com"], "subject": "Hi", "body": "Hello"},
                    "on_error": "stop",
                },
            ],
        },
    )
    from cogniwork.main import app as application

    task = application.state.skills.run(
        UUID(registered["id"]),
        UUID(skill["id"]),
        engine=application.state.task_engine,
        dry_run=True,
        wait=True,
    )
    after = len(getattr(transport, "calls", []))
    send_calls = [
        row
        for row in getattr(transport, "calls", [])[before:after]
        if "messages/send" in str(row.get("url"))
    ]
    assert send_calls == []
    assert task.status.value in {"succeeded", "waiting_approval"}


def test_nested_skill_second_layer_rejected_at_runtime(client, registered):
    headers = auth_header(registered["token"])
    inner = _save(
        client,
        headers,
        {
            "name": "Inner",
            "description": "Leaf",
            "status": "active",
            "workflow": [
                {
                    "id": "s1",
                    "type": "llm",
                    "title": "Do the inner work",
                    "instruction": "Write a line.",
                }
            ],
        },
    )
    mid = _save(
        client,
        headers,
        {
            "name": "Mid",
            "description": "One nest",
            "status": "active",
            "workflow": [
                {
                    "id": "s1",
                    "type": "skill",
                    "title": "Call inner",
                    "skill_id": inner["id"],
                }
            ],
        },
    )
    outer = _save(
        client,
        headers,
        {
            "name": "Outer",
            "description": "Too deep",
            "status": "active",
            "workflow": [
                {
                    "id": "s1",
                    "type": "skill",
                    "title": "Call mid",
                    "skill_id": mid["id"],
                }
            ],
        },
    )
    from cogniwork.main import app

    task = app.state.skills.run(
        UUID(registered["id"]),
        UUID(outer["id"]),
        engine=app.state.task_engine,
        wait=True,
    )
    assert task.status.value == "failed"
    assert "one level" in (task.error or {}).get("message", "").lower()
    assert MAX_NESTING == 1


def test_one_level_nested_skill_runs(client, registered):
    headers = auth_header(registered["token"])
    inner = _save(
        client,
        headers,
        {
            "name": "Inner",
            "description": "Leaf",
            "status": "active",
            "workflow": [
                {
                    "id": "s1",
                    "type": "llm",
                    "title": "Do the inner work",
                    "instruction": "Write a line.",
                }
            ],
        },
    )
    outer = _save(
        client,
        headers,
        {
            "name": "Outer",
            "description": "One nest",
            "status": "active",
            "workflow": [
                {
                    "id": "s1",
                    "type": "skill",
                    "title": "Call inner",
                    "skill_id": inner["id"],
                },
                {
                    "id": "s2",
                    "type": "llm",
                    "title": "Wrap up",
                    "instruction": "Say done.",
                },
            ],
        },
    )
    from cogniwork.main import app

    task = app.state.skills.run(
        UUID(registered["id"]),
        UUID(outer["id"]),
        engine=app.state.task_engine,
        wait=True,
    )
    assert task.status.value == "succeeded"


def test_editor_can_save_unset_tool_draft(client, registered):
    headers = auth_header(registered["token"])
    skill = _save(
        client,
        headers,
        {
            "name": "Pending send",
            "description": "Tool chosen later",
            "workflow": [
                {
                    "id": "s1",
                    "type": "tool",
                    "title": "Send it to the people who need it",
                    "tool": None,
                    "needs_clarification": True,
                    "on_error": "stop",
                }
            ],
        },
    )
    assert skill["status"] == "draft"
    assert skill["workflow"][0]["tool"] is None


def test_templates_are_zero_auth(client, registered):
    headers = auth_header(registered["token"])
    response = client.get(f"{_prefix()}/templates", headers=headers)
    assert response.status_code == 200
    templates = response.json()["templates"]
    assert len(templates) >= 4
    blob = str(templates).lower()
    for name in ("hubspot", "gmail", "slack", "notion"):
        assert name not in blob
