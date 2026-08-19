"""Memory OS：CRUD、检索、确认、摄取、按 Scope 清理、零授权不自动写入。"""

from __future__ import annotations

from uuid import UUID

from cogniwork.core.config import get_settings
from cogniwork.memory.embed import StubEmbeddingProvider, cosine
from cogniwork.memory.extract import drafts_from_text
from cogniwork.memory.ingest import chunk_text
from cogniwork.memory.models import MemoryStatus, MemoryType, SourceType
from cogniwork.memory.service import MemoryService

from .conftest import auth_header


def _prefix() -> str:
    return get_settings().api_prefix


def test_explicit_write_and_physical_delete(client, registered):
    headers = auth_header(registered["token"])
    created = client.post(
        f"{_prefix()}/memories",
        headers=headers,
        json={"type": "semantic", "content": "Our list price is $99 per seat per month."},
    )
    assert created.status_code == 200, created.text
    memory_id = created.json()["id"]
    listed = client.get(f"{_prefix()}/memories", headers=headers)
    assert any(item["id"] == memory_id for item in listed.json()["memories"])

    deleted = client.delete(f"{_prefix()}/memories/{memory_id}", headers=headers)
    assert deleted.status_code == 200
    missing = client.get(f"{_prefix()}/memories/{memory_id}", headers=headers)
    assert missing.status_code == 404
    search = client.post(
        f"{_prefix()}/memories/search",
        headers=headers,
        json={"query": "list price $99"},
    )
    assert all(hit["id"] != memory_id for hit in search.json()["hits"])


def test_stub_search_does_not_promote_unrelated_memories():
    """Hash embeddings are not semantic; unrelated items must stay below the floor."""
    service = MemoryService(embeddings=StubEmbeddingProvider())
    user = UUID("00000000-0000-7000-8000-000000000007")
    service.create(
        user,
        type=MemoryType.SEMANTIC,
        content="The list price is $99 per seat per month.",
    )
    service.create(user, type=MemoryType.PREFERENCE, content="Never use honorifics in email.")
    service.create(user, type=MemoryType.SEMANTIC, content="The office snack budget is $40.")
    scored = service.search_debug(user, "What is our seat price?")
    hits = [row for row in scored if row["score"] >= 0.35]
    texts = [row["content"] for row in hits]
    assert any("$99" in text for text in texts)
    assert all("honorifics" not in text.lower() for text in texts)


def test_hybrid_retrieve_prefers_relevant_memory():
    service = MemoryService(embeddings=StubEmbeddingProvider())
    user = UUID("00000000-0000-7000-8000-000000000001")
    service.create(
        user,
        type=MemoryType.SEMANTIC,
        content="The flagship product is CogniWork at $99 per seat.",
        summary="Pricing",
    )
    service.create(
        user,
        type=MemoryType.SEMANTIC,
        content="The office plant is named Fern.",
        summary="Plant",
    )
    service.create(
        user,
        type=MemoryType.PREFERENCE,
        content="Write reports as tables, not long prose.",
        summary="Tables",
    )
    bundle = service.retrieve(user, "What is our product pricing for a weekly report?")
    texts = [row.item.content for row in bundle.facts + bundle.preferences]
    assert any("99" in text for text in texts)
    assert bundle.xml.startswith("<memory>")
    assert "preferences" in bundle.xml


def test_pending_extract_does_not_auto_activate_without_scope(client, registered):
    """P0-02 验收 3：未授权 auto_write 时，task_extracted 不得直接 active。"""
    headers = auth_header(registered["token"])
    created = client.post(
        f"{_prefix()}/tasks",
        headers=headers,
        json={"message": "Remember: our list price is $99 per seat. Prefer tables."},
    )
    assert created.status_code == 200
    import time

    task_id = created.json()["id"]
    deadline = time.time() + 15
    while time.time() < deadline:
        body = client.get(f"{_prefix()}/tasks/{task_id}", headers=headers).json()
        if body["status"] in {"succeeded", "failed", "cancelled", "timed_out"}:
            break
        time.sleep(0.05)
    pending = client.get(f"{_prefix()}/memories/pending", headers=headers).json()["memories"]
    extracted = [item for item in pending if item["source_type"] == "task_extracted"]
    assert extracted, pending
    active = client.get(
        f"{_prefix()}/memories",
        headers=headers,
        params={"status": "active", "type": "semantic"},
    ).json()["memories"]
    assert all(item["source_type"] != "task_extracted" for item in active)


def test_confirm_then_search(client, registered):
    headers = auth_header(registered["token"])
    # force pending via confirm path
    service = client.app.state.memory
    user = UUID(registered["id"])
    pending = service.create(
        user,
        type=MemoryType.SEMANTIC,
        content="Q3 push channels are LinkedIn and email.",
        source_type=SourceType.TASK_EXTRACTED,
        status=MemoryStatus.PENDING,
        source_ref={"quote": "LinkedIn and email"},
    )
    confirmed = client.post(
        f"{_prefix()}/memories/{pending.id}/confirm",
        headers=headers,
        json={"action": "accept"},
    )
    assert confirmed.json()["status"] == "active"
    hits = client.post(
        f"{_prefix()}/memories/search",
        headers=headers,
        json={"query": "which channels did we push in Q3"},
    ).json()["hits"]
    assert any("LinkedIn" in hit["content"] for hit in hits)


def test_ingest_creates_pending_chunks(client, registered):
    headers = auth_header(registered["token"])
    upload = client.post(
        f"{_prefix()}/files",
        headers=headers,
        files={"file": ("notes.md", b"# Pricing\n\nSeats cost 99 dollars.\n", "text/markdown")},
        data={"persist": "false"},
    )
    ingested = client.post(
        f"{_prefix()}/files/{upload.json()['id']}/ingest",
        headers=headers,
    )
    assert ingested.status_code == 200, ingested.text
    assert ingested.json()["count"] >= 1
    assert ingested.json()["preview"][0]["status"] == "pending"


def test_purge_by_scope_on_revoke(client, registered, registry):
    headers = auth_header(registered["token"])
    scope = "memory:preference:auto_write"
    client.post(
        f"{_prefix()}/consent",
        headers=headers,
        json={
            "scope_key": scope,
            "always_allow": True,
            "consent_text_version": registry.require(scope).consent_text_version,
        },
    )
    service = client.app.state.memory
    user = UUID(registered["id"])
    item = service.create(
        user,
        type=MemoryType.PREFERENCE,
        content="Always use a table for numbers.",
        source_type=SourceType.TASK_EXTRACTED,
        scope_key=scope,
    )
    revoked = client.delete(
        f"{_prefix()}/consent/{scope}",
        headers=headers,
        params={"purge_data": True},
    )
    assert revoked.json()["purge_supported"] is True
    assert revoked.json()["purge_completed"] is True
    assert client.get(f"{_prefix()}/memories/{item.id}", headers=headers).status_code == 404


def test_conflict_marks_exact_duplicate():
    service = MemoryService()
    user = UUID("00000000-0000-7000-8000-000000000002")
    first = service.create(user, type=MemoryType.SEMANTIC, content="Pricing is $79 per seat.")
    second = service.create(user, type=MemoryType.SEMANTIC, content="Pricing is $79 per seat.")
    first = service.get(user, first.id)
    second = service.get(user, second.id)
    assert first.status is MemoryStatus.ACTIVE
    assert second.status is MemoryStatus.REJECTED
    assert second.conflict_with == first.id


def test_chunk_text_keeps_headings():
    text = "# One\n\n" + ("alpha " * 80) + "\n\n# Two\n\n" + ("beta " * 80)
    chunks = chunk_text(text)
    assert len(chunks) >= 2


def test_drafts_from_remember_line():
    drafts = drafts_from_text("Remember: ACME is the parent company.\nPrefer short emails.")
    kinds = {d.type for d in drafts}
    assert MemoryType.SEMANTIC in kinds
    assert MemoryType.PREFERENCE in kinds


def test_cosine_identical_vectors():
    vec = StubEmbeddingProvider().embed(["same text"])[0]
    assert cosine(vec, vec) > 0.99
