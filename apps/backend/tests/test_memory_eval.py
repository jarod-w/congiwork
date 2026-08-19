"""Golden-query retrieval eval (P0-02 §5.2 / §10)."""

from __future__ import annotations

from uuid import UUID

from cogniwork.memory.embed import StubEmbeddingProvider
from cogniwork.memory.models import MemoryType
from cogniwork.memory.service import MemoryService

CASES = [
    ("What is our seat price?", ["$99 per seat"]),
    ("How should weekly reports look?", ["tables, not long prose"]),
    ("Who is the main competitor?", ["WorkBuddy"]),
    ("Which channels did we push in Q3?", ["LinkedIn"]),
    ("What happened last time we wrote the quarterly report?", ["split by channel"]),
]


def _seed(service: MemoryService, user: UUID) -> None:
    facts = [
        (MemoryType.SEMANTIC, "The list price is $99 per seat per month."),
        (MemoryType.PREFERENCE, "Write weekly reports as tables, not long prose."),
        (MemoryType.SEMANTIC, "The main competitor is WorkBuddy."),
        (MemoryType.SEMANTIC, "Q3 push channels were LinkedIn and email."),
        (
            MemoryType.EPISODIC,
            "Last quarterly report, you chose to split by channel instead of region.",
        ),
        (MemoryType.SEMANTIC, "The office snack budget is $40."),
        (MemoryType.PREFERENCE, "Never use honorifics in email."),
    ]
    for kind, content in facts:
        service.create(user, type=kind, content=content)


def test_golden_queries_meet_phase1_floor():
    service = MemoryService(embeddings=StubEmbeddingProvider())
    user = UUID("00000000-0000-7000-8000-000000000042")
    _seed(service, user)
    hits_at_8 = 0
    retrieved_relevant = 0
    retrieved_total = 0
    for query, needles in CASES:
        hits = service.search_debug(user, query)
        texts = [hit["content"] for hit in hits if hit["score"] >= 0.35][:8]
        retrieved_total += len(texts)
        matched = any(any(needle.lower() in text.lower() for needle in needles) for text in texts)
        if matched:
            hits_at_8 += 1
        retrieved_relevant += sum(
            1 for text in texts if any(needle.lower() in text.lower() for needle in needles)
        )
    recall = hits_at_8 / len(CASES)
    precision = retrieved_relevant / retrieved_total if retrieved_total else 0.0
    assert recall >= 0.8, f"recall@8={recall:.2f}"
    assert precision >= 0.5, f"precision@8={precision:.2f}"
