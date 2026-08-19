"""TaskEngine / 工具 / SSE 单测。"""

from __future__ import annotations

import io
import json
import time

from openpyxl import Workbook

from cogniwork.consent.models import Risk
from cogniwork.core.config import get_settings
from cogniwork.runtime.tools.builtin import BUILTIN_TOOLS
from cogniwork.runtime.weekly_report import build_weekly_report


def _prefix() -> str:
    return get_settings().api_prefix


def _xlsx_bytes() -> bytes:
    wb = Workbook()
    sheet = wb.active
    sheet.append(["Channel", "This week", "Last week"])
    sheet.append(["Email", 50, 40])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_builtin_tools_are_unscoped():
    """L1 内置工具不登记 Scope。给它们加 Scope 会让零授权 E2E 挂掉。"""
    for spec in BUILTIN_TOOLS:
        assert spec.provider == "builtin"
        assert spec.scope_key is None
        assert spec.risk in {Risk.READ, Risk.WRITE}


def test_weekly_report_contains_takeaways():
    markdown, xlsx = build_weekly_report(_xlsx_bytes(), "channels.xlsx")
    assert "Weekly report" in markdown
    assert "Email" in markdown
    assert xlsx.startswith(b"PK")


def test_create_task_requires_auth(client):
    response = client.post(f"{_prefix()}/tasks", json={"message": "hello"})
    assert response.status_code == 401


def test_upload_rejects_unsupported_type(client, registered):
    response = client.post(
        f"{_prefix()}/files",
        headers={"Authorization": f"Bearer {registered['token']}"},
        files={"file": ("photo.png", b"not-an-image", "image/png")},
    )
    assert response.status_code == 400


def test_task_sse_replays_from_seq(client, registered):
    headers = {"Authorization": f"Bearer {registered['token']}"}
    upload = client.post(
        f"{_prefix()}/files",
        headers=headers,
        files={
            "file": (
                "channels.xlsx",
                _xlsx_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"persist": "false"},
    )
    created = client.post(
        f"{_prefix()}/tasks",
        headers=headers,
        json={"message": "Turn this into a weekly report", "file_ids": [upload.json()["id"]]},
    )
    task_id = created.json()["id"]
    deadline = time.time() + 15
    while time.time() < deadline:
        body = client.get(f"{_prefix()}/tasks/{task_id}", headers=headers).json()
        if body["status"] in {"succeeded", "failed", "cancelled", "timed_out"}:
            break
        time.sleep(0.05)
    url = f"{_prefix()}/tasks/{task_id}/events?from_seq=0"
    with client.stream("GET", url, headers=headers) as stream:
        raw = b"".join(stream.iter_bytes())
    text = raw.decode()
    assert "task.created" in text
    assert "task.finished" in text
    seqs = []
    for line in text.splitlines():
        if line.startswith("data: "):
            seqs.append(json.loads(line[6:])["seq"])
    assert seqs == sorted(seqs)
    assert seqs == list(range(1, len(seqs) + 1))


def test_model_router_falls_back_to_stub_without_keys():
    from cogniwork.runtime.llm.router import ModelRouter, RoutingRequest
    from cogniwork.runtime.llm.stub import StubLLM

    router = ModelRouter()
    client = router.client_for(
        RoutingRequest("weekly_report", 0, False, True, "interactive", "standard")
    )
    assert isinstance(client, StubLLM)
    chosen = router.choose(RoutingRequest(None, 0, False, True, "interactive", "standard"))
    assert chosen.vendor == "stub"
