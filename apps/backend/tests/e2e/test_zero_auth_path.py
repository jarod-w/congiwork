"""零授权核心路径 E2E（P0-07 §8.3）。

注册 → 跳过全部访谈 → 上传 xlsx → 发起「整理成周报」→ 拿到产物 → 下载

全程 consent_record 必须为空。这条挂了等同 P0 缺陷（硬约束 5）。
访谈（P0-01）本阶段尚未落地，因此「跳过」= 注册后不被要求进入访谈。
"""

from __future__ import annotations

import io
import time

from openpyxl import Workbook

from cogniwork.core.config import get_settings

TERMINAL = {"succeeded", "failed", "cancelled", "timed_out"}


def _prefix() -> str:
    return get_settings().api_prefix


def _xlsx_bytes() -> bytes:
    wb = Workbook()
    sheet = wb.active
    sheet.title = "Channels"
    sheet.append(["Channel", "This week", "Last week"])
    sheet.append(["Email", 120, 100])
    sheet.append(["LinkedIn", 80, 90])
    sheet.append(["Paid ads", 200, 150])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _wait_for_task(client, token: str, task_id: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    deadline = time.time() + 15
    last = None
    while time.time() < deadline:
        response = client.get(f"{_prefix()}/tasks/{task_id}", headers=headers)
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] in TERMINAL:
            return last
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} did not finish: {last}")


def test_zero_auth_weekly_report_path(client):
    prefix = _prefix()
    register = client.post(
        f"{prefix}/auth/register",
        json={"email": "zero@example.com", "password": "a-strong-password"},
    )
    assert register.status_code == 201, register.text
    token = register.json()["access_token"]
    user_id = register.json()["account"]["id"]
    headers = {"Authorization": f"Bearer {token}"}

    # 注册后即可派活：没有访谈闸门。
    me = client.get(f"{prefix}/auth/me", headers=headers)
    assert me.status_code == 200

    upload = client.post(
        f"{prefix}/files",
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
    assert upload.status_code == 200, upload.text
    file_id = upload.json()["id"]

    created = client.post(
        f"{prefix}/tasks",
        headers=headers,
        json={
            "message": "Turn this spreadsheet into a weekly report",
            "file_ids": [file_id],
            "surface": "web",
        },
    )
    assert created.status_code == 200, created.text
    task_id = created.json()["id"]

    task = _wait_for_task(client, token, task_id)
    assert task["status"] == "succeeded", task
    assert task["artifacts"], "expected at least one artifact"
    assert any(item["filename"].endswith((".md", ".xlsx")) for item in task["artifacts"])

    artifact_id = task["artifacts"][0]["id"]
    download = client.get(f"{prefix}/artifacts/{artifact_id}", headers=headers)
    assert download.status_code == 200
    assert len(download.content) > 0
    assert "attachment" in download.headers.get("content-disposition", "")

    store = client.app.state.consent_store
    assert store.record_count(user_id) == 0, "zero-auth path must not write consent_record"


def test_zero_auth_path_does_not_require_any_scope(client):
    """即使用户从未看过授权页，任务也能成功。"""
    prefix = _prefix()
    register = client.post(
        f"{prefix}/auth/register",
        json={"email": "skip-scopes@example.com", "password": "a-strong-password"},
    )
    token = register.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    scopes = client.get(f"{prefix}/scopes", headers=headers)
    assert scopes.status_code == 200
    assert scopes.json()["scopes"]

    upload = client.post(
        f"{prefix}/files",
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
        f"{prefix}/tasks",
        headers=headers,
        json={"message": "整理成周报", "file_ids": [upload.json()["id"]]},
    )
    task = _wait_for_task(client, token, created.json()["id"])
    assert task["status"] == "succeeded"
    assert client.app.state.consent_store.record_count(register.json()["account"]["id"]) == 0
