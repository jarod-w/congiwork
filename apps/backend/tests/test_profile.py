"""Personal Profile: CRUD, interview skip, pending never injected, archive (P0-01)."""

from __future__ import annotations

from uuid import UUID

from cogniwork.core.config import get_settings
from cogniwork.profile.models import FieldStatus, ProfileDraft
from cogniwork.profile.service import ProfileService

from .conftest import auth_header


def _prefix() -> str:
    return get_settings().api_prefix


def test_skip_interview_leaves_core_path_open(client, registered):
    headers = auth_header(registered["token"])
    skipped = client.post(
        f"{_prefix()}/profile/interview/skip",
        headers=headers,
        json={"scope": "all"},
    )
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["session"]["status"] == "skipped"
    me = client.get(f"{_prefix()}/auth/me", headers=headers)
    assert me.status_code == 200


def test_extracted_pending_is_not_injected():
    service = ProfileService()
    user = UUID("00000000-0000-7000-8000-000000000011")
    service.propose(
        user,
        [ProfileDraft(key="role", value="Secret spy", evidence={"task_id": "t1"})],
    )
    card = service.render_card(user)
    assert "Secret spy" not in card
    assert "<user_profile>" not in card
    pending = service.get(user)["fields"]
    assert pending[0]["status"] == "pending"
    confirmed = service.confirm(user, UUID(pending[0]["id"]), action="accept")
    assert confirmed.status is FieldStatus.ACTIVE
    card = service.render_card(user)
    assert "Secret spy" in card


def test_manual_field_and_delete_clears_card(client, registered):
    headers = auth_header(registered["token"])
    patched = client.patch(
        f"{_prefix()}/profile/fields/role",
        headers=headers,
        json={"value": "Marketing Director"},
    )
    assert patched.status_code == 200, patched.text
    exported = client.get(f"{_prefix()}/profile/export", headers=headers)
    assert "Marketing Director" in exported.text
    deleted = client.delete(f"{_prefix()}/profile", headers=headers)
    assert deleted.status_code == 200
    again = client.get(f"{_prefix()}/profile", headers=headers)
    assert again.json()["fields"] == []


def test_archive_and_create_keeps_old_readable(client, registered):
    headers = auth_header(registered["token"])
    client.patch(
        f"{_prefix()}/profile/fields/role",
        headers=headers,
        json={"value": "Old role"},
    )
    first = client.get(f"{_prefix()}/profile", headers=headers).json()
    archived = client.post(
        f"{_prefix()}/profile/archive",
        headers=headers,
        json={"reason": "changed company"},
    )
    assert archived.status_code == 200, archived.text
    body = client.get(f"{_prefix()}/profile", headers=headers).json()
    assert body["profile"]["id"] != first["profile"]["id"]
    assert body["archived"]
    assert body["archived"][0]["archive_reason"] == "changed company"
    assert all(item["status"] != "active" or item.get("key") != "role" for item in body["fields"])


def test_interview_round_one_and_first_task_creates_task(client, registered):
    headers = auth_header(registered["token"])
    started = client.post(f"{_prefix()}/profile/interview/start", headers=headers)
    assert started.status_code == 200, started.text
    assert started.json()["question"]["key"] == "role"
    client.post(
        f"{_prefix()}/profile/interview/answer",
        headers=headers,
        json={"selected": ["growth"], "text": "Growth"},
    )
    client.post(
        f"{_prefix()}/profile/interview/answer",
        headers=headers,
        json={"text": "B2B SaaS, mid-market shops"},
    )
    third = client.post(
        f"{_prefix()}/profile/interview/answer",
        headers=headers,
        json={"text": "Turn last week's channel numbers into a weekly report"},
    )
    assert third.status_code == 200, third.text
    assert third.json().get("task", {}).get("id")


def test_delete_profile_then_task_has_empty_card(client, registered):
    headers = auth_header(registered["token"])
    client.patch(
        f"{_prefix()}/profile/fields/role",
        headers=headers,
        json={"value": "Should vanish"},
    )
    client.delete(f"{_prefix()}/profile", headers=headers)
    created = client.post(
        f"{_prefix()}/tasks",
        headers=headers,
        json={"message": "Turn this note into a weekly report."},
    )
    assert created.status_code == 200, created.text
    import time

    time.sleep(0.2)
    ctx = client.get(f"{_prefix()}/tasks/{created.json()['id']}/context", headers=headers)
    assert ctx.status_code == 200
    assert "Should vanish" not in (ctx.json().get("profile_card") or "")
