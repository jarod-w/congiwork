# Memory retrieval eval (P0-02 §5.2)

Phase 1 target: `recall@8 ≥ 0.8`, `precision@8 ≥ 0.5` on this golden set.

The pytest module `tests/test_memory_eval.py` loads the cases below against the
in-process MemoryService + stub embedding provider. Re-run it whenever retrieval
weights, scoring, or chunking change.

Stub embeddings are deterministic hashes, so this is a **logic** regression test,
not a model-quality benchmark. When an OpenAI (or other 1024-d) provider is
configured, run the same cases against a seeded fixture dump before shipping.

| id | query | must retrieve (content contains) |
|---|---|---|
| g1 | What is our seat price? | $99 per seat |
| g2 | How should weekly reports look? | tables, not long prose |
| g3 | Who is the main competitor? | WorkBuddy |
| g4 | Which channels did we push in Q3? | LinkedIn |
| g5 | What happened last time we wrote the quarterly report? | split by channel |

## Chinese queries: no lexical signal, by decision

`_lexical_tokens` splits on whitespace, so a Chinese sentence is one token.
`_lexical_overlap("席位价格", "标准席位价格是…")` is **0** — a query that is a
literal substring of the stored memory scores nothing. For Chinese, the
`0.25 * lexical` term of the hybrid score is dead weight and recall rests
entirely on the vector half.

Phase 1 does not add a tokenizer. The market is English-speaking (A2), so this
does not affect the exit criteria, and `pg_jieba` is a PostgreSQL extension the
official `postgres:16` image does not ship — pulling it in would tie CI and the
production image to a custom build, the same reason deviation 10 keeps pgvector
out of Phase 1.

If a Chinese market opens in Phase 2, evaluate **CJK character bigrams** first:
no dictionary, no extension, and it drops straight into `_lexical_tokens`. Full
segmentation is the step after that, not the first one.

`test_chinese_queries_get_no_lexical_signal_without_a_tokenizer` pins the
measurement. Check whether it still reads 0 before reopening the decision.
