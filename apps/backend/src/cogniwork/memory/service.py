"""MemoryService —— CRUD、混合检索、上下文组装、冲突、抽取入口（P0-02）。"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from cogniwork.core.clock import now
from cogniwork.core.errors import InvalidRequest, NotFound
from cogniwork.core.ids import new_id

from .embed import STUB_MODEL, EmbeddingProvider, StubEmbeddingProvider, cosine
from .models import (
    EpisodeOutcome,
    EpisodicRecord,
    MemoryBundle,
    MemoryDraft,
    MemoryItem,
    MemoryStatus,
    MemoryType,
    ScoredMemory,
    SourceType,
)
from .store import InMemoryMemoryStore

# 自动写入偏好需要这条 Scope。这里只读授权记录的当前动作，
# 不走运行时工具调用链上的唯一检查点。
AUTO_WRITE_SCOPE = "memory:preference:auto_write"

_SCORE_FLOOR = 0.35
_CONFLICT_COSINE = 0.88
_HALF_LIFE_DAYS = 90.0
_TOKEN_BUDGET = {
    MemoryType.PREFERENCE: 400,
    MemoryType.SEMANTIC: 1100,
    MemoryType.EPISODIC: 500,
}


class MemoryService:
    def __init__(
        self,
        store: Any | None = None,
        embeddings: EmbeddingProvider | None = None,
        consent_store: Any | None = None,
        budget_tokens: int = 2000,
    ) -> None:
        self.store = store or InMemoryMemoryStore()
        self.embeddings = embeddings or StubEmbeddingProvider()
        self._consent_store = consent_store
        self.budget_tokens = budget_tokens

    def auto_write_enabled(self, user_id: UUID) -> bool:
        if self._consent_store is None:
            return False
        state = self._consent_store.current(str(user_id), AUTO_WRITE_SCOPE)
        return state is not None and state.action.value == "granted"

    def create(
        self,
        user_id: UUID,
        *,
        type: MemoryType,
        content: str,
        summary: str | None = None,
        subtype: str | None = None,
        importance: int = 3,
        source_type: SourceType = SourceType.USER_EXPLICIT,
        source_ref: dict[str, Any] | None = None,
        scope_key: str | None = None,
        status: MemoryStatus = MemoryStatus.ACTIVE,
    ) -> MemoryItem:
        text = content.strip()
        if not text:
            raise InvalidRequest("Memory content cannot be empty.")
        if not 1 <= importance <= 5:
            raise InvalidRequest("Importance must be between 1 and 5.")
        created = now()
        item = MemoryItem(
            id=new_id(),
            user_id=user_id,
            type=type,
            subtype=subtype,
            content=text,
            summary=(summary or text[:120]).strip(),
            embedding=None,
            embed_model=None,
            importance=importance,
            confidence=1.0,
            source_type=source_type,
            source_ref=source_ref,
            scope_key=scope_key,
            status=status,
            superseded_by=None,
            conflict_with=None,
            valid_from=created,
            valid_to=None,
            last_used_at=None,
            use_count=0,
            created_at=created,
            updated_at=created,
        )
        self._embed(item)
        if item.status is MemoryStatus.ACTIVE:
            return self._activate(item)
        return self.store.upsert(item)

    def get(self, user_id: UUID, memory_id: UUID) -> MemoryItem:
        item = self.store.get(user_id, memory_id)
        if item is None:
            raise NotFound("Memory not found.")
        return item

    def list(
        self,
        user_id: UUID,
        *,
        type: MemoryType | None = None,
        status: MemoryStatus | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryItem]:
        return self.store.list(
            user_id, type=type, status=status, query=query, limit=limit, offset=offset
        )

    def pending(self, user_id: UUID) -> list[MemoryItem]:
        return self.store.list(user_id, status=MemoryStatus.PENDING, limit=100)

    def update(
        self,
        user_id: UUID,
        memory_id: UUID,
        *,
        content: str | None = None,
        importance: int | None = None,
        summary: str | None = None,
    ) -> MemoryItem:
        item = self.get(user_id, memory_id)
        if content is not None:
            text = content.strip()
            if not text:
                raise InvalidRequest("Memory content cannot be empty.")
            item.content = text
            if summary is None:
                item.summary = text[:120]
            self._embed(item)
        if summary is not None:
            item.summary = summary.strip() or item.summary
        if importance is not None:
            if not 1 <= importance <= 5:
                raise InvalidRequest("Importance must be between 1 and 5.")
            item.importance = importance
        item.updated_at = now()
        return self.store.upsert(item)

    def delete(self, user_id: UUID, memory_id: UUID) -> None:
        if not self.store.delete(user_id, memory_id):
            raise NotFound("Memory not found.")

    def confirm(
        self,
        user_id: UUID,
        memory_id: UUID,
        *,
        accept: bool,
        content: str | None = None,
    ) -> MemoryItem:
        item = self.get(user_id, memory_id)
        if item.status is not MemoryStatus.PENDING:
            raise InvalidRequest("Only pending memories can be confirmed.")
        if not accept:
            item.status = MemoryStatus.REJECTED
            item.updated_at = now()
            return self.store.upsert(item)
        if content is not None:
            item.content = content.strip() or item.content
            item.summary = item.content[:120]
            self._embed(item)
        item.status = MemoryStatus.ACTIVE
        item.updated_at = now()
        return self._activate(item)

    def propose(
        self,
        user_id: UUID,
        drafts: list[MemoryDraft],
        source: dict[str, Any] | None = None,
    ) -> list[MemoryItem]:
        """通道 ②：候选确认。未授权自动写入时偏好也走这里。"""
        created: list[MemoryItem] = []
        ranked = sorted(drafts, key=lambda draft: draft.importance, reverse=True)[:5]
        auto = self.auto_write_enabled(user_id)
        for draft in ranked:
            status = MemoryStatus.PENDING
            if (
                auto
                and draft.type is MemoryType.PREFERENCE
                and draft.source_type is SourceType.TASK_EXTRACTED
            ):
                status = MemoryStatus.ACTIVE
            ref = dict(source or {})
            if draft.evidence_quote:
                ref["quote"] = draft.evidence_quote
            created.append(
                self.create(
                    user_id,
                    type=draft.type,
                    content=draft.content,
                    summary=draft.summary,
                    subtype=draft.subtype,
                    importance=draft.importance,
                    source_type=draft.source_type,
                    source_ref=ref or None,
                    scope_key=draft.scope_key
                    or (AUTO_WRITE_SCOPE if draft.type is MemoryType.PREFERENCE else None),
                    status=status,
                )
            )
        return created

    def record_episode(self, task: Any, user_edits: list[dict[str, Any]] | None = None) -> UUID:
        """任务终态落一条 Episodic。无需授权 —— 这是系统自己做过什么。"""
        existing = self.store.get_episode_by_task(task.user_id, task.id)
        if existing is not None:
            return existing.memory_id
        outcome = _outcome_for(getattr(task.status, "value", str(task.status)))
        tools = sorted(
            {
                step.title
                for step in (task.steps or [])
                if getattr(step.type, "value", step.type) == "tool"
            }
        )
        duration_ms = None
        if task.started_at and task.ended_at:
            duration_ms = int((task.ended_at - task.started_at).total_seconds() * 1000)
        title = task.title or "Untitled task"
        content = f"You asked me to {title.rstrip('.')}. Outcome: {outcome.value}."
        if tools:
            content += f" Tools used: {', '.join(tools)}."
        item = self.create(
            task.user_id,
            type=MemoryType.EPISODIC,
            content=content,
            summary=title,
            subtype=task.intent,
            importance=3,
            source_type=SourceType.SYSTEM,
            source_ref={"task_id": str(task.id)},
            status=MemoryStatus.ACTIVE,
        )
        record = EpisodicRecord(
            id=new_id(),
            memory_id=item.id,
            user_id=task.user_id,
            task_id=task.id,
            title=title,
            intent=task.intent,
            tools_used=tools,
            skill_id=task.skill_id,
            outcome=outcome,
            decisions=[],
            user_edits=list(user_edits or []),
            duration_ms=duration_ms,
            started_at=task.started_at or task.created_at,
            ended_at=task.ended_at,
        )
        self.store.put_episode(record)
        return item.id

    def retrieve(self, user_id: UUID, query: str, budget_tokens: int | None = None) -> MemoryBundle:
        budget = budget_tokens or self.budget_tokens
        query_vec = self.embeddings.embed([query])[0] if query.strip() else None
        by_id: dict[UUID, ScoredMemory] = {}

        for mem_type in MemoryType:
            for item in self.store.active_of_type(user_id, mem_type)[:30]:
                scored = self._score(item, query, query_vec)
                if scored.score >= _SCORE_FLOOR:
                    by_id[item.id] = scored

        for item in self.store.lexical_search(user_id, query, limit=20):
            scored = self._score(item, query, query_vec)
            existing = by_id.get(item.id)
            if existing is None or scored.score > existing.score:
                if scored.score >= _SCORE_FLOOR:
                    by_id[item.id] = scored

        ranked = sorted(by_id.values(), key=lambda row: row.score, reverse=True)[:8]
        preferences: list[ScoredMemory] = []
        facts: list[ScoredMemory] = []
        past: list[ScoredMemory] = []
        used = 0
        caps = {
            MemoryType.PREFERENCE: _TOKEN_BUDGET[MemoryType.PREFERENCE],
            MemoryType.SEMANTIC: _TOKEN_BUDGET[MemoryType.SEMANTIC],
            MemoryType.EPISODIC: _TOKEN_BUDGET[MemoryType.EPISODIC],
        }
        # Preference: fill all that fit. Others follow score order.
        pref_items = [
            self._score(item, query, query_vec)
            for item in self.store.active_of_type(user_id, MemoryType.PREFERENCE)
        ]
        pref_items.sort(key=lambda row: (-row.item.importance, -row.score))
        pref_budget = min(caps[MemoryType.PREFERENCE], budget)
        for scored in pref_items:
            tokens = _token_count(scored.item.content)
            if used + tokens > pref_budget:
                continue
            preferences.append(scored)
            used += tokens

        remaining = max(0, budget - used)
        for scored in ranked:
            if scored.item.type is MemoryType.PREFERENCE:
                continue
            tokens = _token_count(scored.item.content)
            bucket = facts if scored.item.type is MemoryType.SEMANTIC else past
            cap = caps[scored.item.type]
            already = sum(_token_count(row.item.content) for row in bucket)
            if already + tokens > cap or used + tokens > remaining + used:
                continue
            if used + tokens > budget:
                continue
            bucket.append(scored)
            used += tokens

        if not past:
            for episode in self.store.recent_episodes(user_id, limit=2):
                item = self.store.get(user_id, episode.memory_id)
                if item is None or item.status is not MemoryStatus.ACTIVE:
                    continue
                tokens = _token_count(item.content)
                if used + tokens > budget:
                    break
                past.append(self._score(item, query, query_vec))
                used += tokens

        xml = _assemble_xml(preferences, facts, past)
        self._touch([row.item for row in preferences + facts + past])
        return MemoryBundle(
            preferences=preferences,
            facts=facts,
            past=past,
            xml=xml,
            used_tokens=used,
        )

    def search_debug(self, user_id: UUID, query: str) -> list[dict[str, Any]]:
        bundle_like = []
        query_vec = self.embeddings.embed([query])[0] if query.strip() else None
        seen: set[UUID] = set()
        for mem_type in MemoryType:
            for item in self.store.active_of_type(user_id, mem_type):
                if item.id in seen:
                    continue
                seen.add(item.id)
                scored = self._score(item, query, query_vec)
                bundle_like.append(
                    {
                        "id": str(item.id),
                        "type": item.type.value,
                        "summary": item.summary,
                        "content": item.content,
                        "score": round(scored.score, 4),
                        "cosine": round(scored.cosine, 4),
                        "lexical": round(scored.lexical, 4),
                        "recency": round(scored.recency, 4),
                        "importance": round(scored.importance, 4),
                    }
                )
        bundle_like.sort(key=lambda row: row["score"], reverse=True)
        return bundle_like[:20]

    def purge_by_scope(self, user_id: UUID, scope_key: str) -> int:
        return self.store.delete_by_scope(user_id, scope_key)

    def purge_all(self, user_id: UUID) -> int:
        return self.store.delete_all(user_id)

    def export(self, user_id: UUID) -> dict[str, Any]:
        items = self.store.list(user_id, limit=10_000)
        return {
            "memories": [memory_out(item) for item in items],
            "count": len(items),
        }

    def mark_not_useful(self, user_id: UUID, memory_id: UUID) -> MemoryItem:
        item = self.get(user_id, memory_id)
        item.importance = max(1, item.importance - 1)
        item.updated_at = now()
        return self.store.upsert(item)

    def _embed(self, item: MemoryItem) -> None:
        vector = self.embeddings.embed([item.content])[0]
        item.embedding = vector
        item.embed_model = getattr(self.embeddings, "model", None)

    def _activate(self, item: MemoryItem) -> MemoryItem:
        """写入 active 前做冲突检测（P0-02 §5.4）。"""
        if item.embedding is None:
            self._embed(item)
        nearest: MemoryItem | None = None
        best = 0.0
        for other in self.store.active_of_type(item.user_id, item.type):
            if other.id == item.id:
                continue
            sim = cosine(item.embedding, other.embedding)
            if sim > best:
                best = sim
                nearest = other
        if nearest is None or best < _CONFLICT_COSINE:
            item.status = MemoryStatus.ACTIVE
            return self.store.upsert(item)
        relation = _relation(item.content, nearest.content)
        if relation == "duplicate":
            nearest.updated_at = now()
            self.store.upsert(nearest)
            item.status = MemoryStatus.REJECTED
            item.conflict_with = nearest.id
            item.updated_at = now()
            return self.store.upsert(item)
        if relation == "supersedes":
            nearest.status = MemoryStatus.SUPERSEDED
            nearest.superseded_by = item.id
            nearest.valid_to = now()
            nearest.updated_at = now()
            self.store.upsert(nearest)
            item.status = MemoryStatus.ACTIVE
            return self.store.upsert(item)
        if relation == "conflict":
            item.status = MemoryStatus.ACTIVE
            item.conflict_with = nearest.id
            stored = self.store.upsert(item)
            nearest.conflict_with = stored.id
            nearest.updated_at = now()
            self.store.upsert(nearest)
            return stored
        item.status = MemoryStatus.ACTIVE
        return self.store.upsert(item)

    def _score(self, item: MemoryItem, query: str, query_vec: list[float] | None) -> ScoredMemory:
        cos = cosine(query_vec, item.embedding) if query_vec else 0.0
        lexical = _lexical_overlap(query, item.content)
        recency = _recency(item.updated_at)
        importance = item.importance / 5.0
        # Hash embeddings have no semantics. Using them as cosine would
        # promote unrelated memories above the retrieval floor.
        if getattr(self.embeddings, "model", None) == STUB_MODEL:
            semantic = lexical
        else:
            semantic = max(_norm(cos), lexical)
        score = 0.55 * semantic + 0.25 * lexical + 0.10 * recency + 0.10 * importance
        return ScoredMemory(
            item=item,
            score=score,
            cosine=cos,
            lexical=lexical,
            recency=recency,
            importance=importance,
        )

    def _touch(self, items: list[MemoryItem]) -> None:
        stamped = now()
        for item in items:
            item.last_used_at = stamped
            item.use_count += 1
            item.updated_at = item.updated_at
            self.store.upsert(item)


def memory_out(item: MemoryItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "type": item.type.value,
        "subtype": item.subtype,
        "content": item.content,
        "summary": item.summary,
        "importance": item.importance,
        "confidence": item.confidence,
        "source_type": item.source_type.value,
        "source_ref": item.source_ref,
        "scope_key": item.scope_key,
        "status": item.status.value,
        "superseded_by": str(item.superseded_by) if item.superseded_by else None,
        "conflict_with": str(item.conflict_with) if item.conflict_with else None,
        "use_count": item.use_count,
        "last_used_at": item.last_used_at.isoformat() if item.last_used_at else None,
        "valid_from": item.valid_from.isoformat(),
        "valid_to": item.valid_to.isoformat() if item.valid_to else None,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def _token_count(text: str) -> int:
    return max(1, len(text) // 4)


def _norm(value: float) -> float:
    return max(0.0, min(1.0, (value + 1.0) / 2.0)) if value < 0 else max(0.0, min(1.0, value))


def _lexical_overlap(query: str, content: str) -> float:
    q = _lexical_tokens(query)
    if not q:
        return 0.0
    c = _lexical_tokens(content)
    return len(q & c) / len(q)


def _lexical_tokens(text: str) -> set[str]:
    out: set[str] = set()
    cleaned = text.lower().replace("/", " ").replace("-", " ").replace("$", " ")
    for raw in cleaned.split():
        tok = raw.strip(".,?!:;\"'()[]")
        if not tok:
            continue
        # Keep short tokens that carry digits (q3, 99) so golden queries hit.
        if len(tok) >= 4 or any(ch.isdigit() for ch in tok):
            out.add(tok)
    return out


def _recency(updated_at) -> float:
    age = max(0.0, (now() - updated_at).total_seconds() / 86400.0)
    return 0.5 ** (age / _HALF_LIFE_DAYS)


def _relation(new_content: str, old_content: str) -> str:
    new_l = new_content.strip().lower()
    old_l = old_content.strip().lower()
    if new_l == old_l:
        return "duplicate"
    if old_l in new_l or (
        len(new_l) > len(old_l) * 1.2 and _lexical_overlap(old_content, new_content) > 0.6
    ):
        return "supersedes"
    if _lexical_overlap(new_content, old_content) > 0.5:
        return "conflict"
    return "unrelated"


def _outcome_for(status: str) -> EpisodeOutcome:
    if status == "succeeded":
        return EpisodeOutcome.SUCCEEDED
    if status == "failed":
        return EpisodeOutcome.FAILED
    if status == "cancelled":
        return EpisodeOutcome.CANCELLED
    return EpisodeOutcome.PARTIAL


def _assemble_xml(
    preferences: list[ScoredMemory],
    facts: list[ScoredMemory],
    past: list[ScoredMemory],
) -> str:
    pref = " ".join(row.item.content.rstrip(".") + "." for row in preferences) or "None recorded."
    fact_lines = []
    for row in facts:
        source = _source_label(row.item)
        fact_lines.append(f"- {row.item.content} ({source})")
    fact_block = "\n  ".join(fact_lines) if fact_lines else "- None retrieved."
    past_bits = []
    for row in past:
        past_bits.append(row.item.content)
    past_block = " ".join(past_bits) or "No similar past tasks."
    return (
        "<memory>\n"
        f"  <preferences>{pref}</preferences>\n"
        f"  <facts>\n  {fact_block}\n  </facts>\n"
        f"  <past>{past_block}</past>\n"
        "</memory>"
    )


def _source_label(item: MemoryItem) -> str:
    ref = item.source_ref or {}
    if ref.get("quote"):
        return f"you said: {ref['quote'][:80]}"
    if ref.get("filename"):
        page = ref.get("page")
        extra = f" p{page}" if page else ""
        return f"{ref['filename']}{extra}"
    if ref.get("task_id"):
        return "a previous task"
    if item.source_type is SourceType.USER_EXPLICIT:
        return "you told me"
    return item.source_type.value


# timedelta imported for potential retention jobs; keep the name used in cleanup.
def retention_cutoff(months: int):
    return now() - timedelta(days=30 * months)
