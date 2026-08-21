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


def test_chinese_queries_get_no_lexical_signal_without_a_tokenizer():
    """结掉 `P0-02` §12 待决 1（是否投入中文分词）—— 用一次可复现的测量，不靠印象。

    现状：lexical 分量按空白切词。中文一句话是一个 token，即使查询串是记忆正文的
    子串（「席位价格」⊂「标准席位价格是…」）重合度也是 0。也就是说中文检索
    **完全由向量召回承担**，混合检索的 0.25 权重那一半是空的。

    结论仍是 Phase 1 不投入分词（A2：目标市场是海外英语市场），理由与代价写在
    `docs/eval/memory-retrieval.md`。这条测试的作用是：将来要推翻这个决定时，
    先看它是否还是 0 —— 而不是重新猜一遍。
    """
    from cogniwork.memory.service import _lexical_overlap

    assert _lexical_overlap("What is our seat price?", "The list price is $99 per seat.") > 0.5
    assert _lexical_overlap("我们的席位价格是多少", "标准席位价格是每人每月 99 美元。") == 0.0
    # 连子串都拿不到分 —— 不是「分词不够好」，是这一路完全没有信号。
    assert _lexical_overlap("席位价格", "标准席位价格是每人每月 99 美元。") == 0.0
