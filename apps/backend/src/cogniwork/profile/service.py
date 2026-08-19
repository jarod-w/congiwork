"""ProfileService — CRUD, interview, card render, cache (P0-01 §6)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from cogniwork.core.clock import now
from cogniwork.core.config import get_settings
from cogniwork.core.errors import InvalidRequest, NotFound
from cogniwork.core.ids import new_id

from .bank import (
    InterviewQuestion,
    estimate_tokens,
    load_bank,
    pick_locale,
    should_ask,
)
from .models import (
    ARRAY_KEYS,
    CARD_TOKEN_BUDGET,
    INJECT_WEIGHT,
    FieldSource,
    FieldStatus,
    InterviewSession,
    InterviewStatus,
    Profile,
    ProfileDraft,
    ProfileField,
    clamp_value,
    normalize_key,
)
from .store import InMemoryProfileStore

CACHE_TTL_SECONDS = 7 * 24 * 60 * 60


class ProfileService:
    def __init__(self, store: Any | None = None, redis: Any | None = None) -> None:
        self.store = store or InMemoryProfileStore()
        self._redis = redis
        self._memory_cache: dict[str, str] = {}
        self._bank = load_bank()

    def ensure_active(self, user_id: UUID) -> Profile:
        existing = self.store.active_profile(user_id)
        if existing is not None:
            return existing
        created = now()
        profile = Profile(
            id=new_id(),
            user_id=user_id,
            version=1,
            completed=False,
            created_at=created,
            updated_at=created,
        )
        return self.store.upsert_profile(profile)

    def get(self, user_id: UUID, *, include_archived: bool = False) -> dict[str, Any]:
        profile = self.store.active_profile(user_id)
        if profile is None:
            profile = self.ensure_active(user_id)
        fields = self.store.list_fields(profile.id)
        session = self.store.latest_session(profile.id)
        archived = self.store.list_profiles(user_id) if include_archived else []
        return {
            "profile": profile_out(profile),
            "fields": [field_out(item) for item in fields],
            "interview": session_out(session) if session else None,
            "archived": [profile_out(item) for item in archived if item.archived_at is not None],
        }

    def upsert_field(
        self,
        user_id: UUID,
        key: str,
        value: Any,
        *,
        source: FieldSource = FieldSource.MANUAL,
        status: FieldStatus = FieldStatus.ACTIVE,
        evidence: dict[str, Any] | None = None,
        confidence: float = 1.0,
    ) -> ProfileField:
        profile = self.ensure_active(user_id)
        key = normalize_key(key)
        value = _coerce(key, clamp_value(value))
        if value in ("", [], {}, None):
            raise InvalidRequest("Field value cannot be empty.")
        created = now()
        if status is FieldStatus.ACTIVE:
            current = self.store.field_by_key(profile.id, key, FieldStatus.ACTIVE)
            if current is not None:
                self.store.delete_field(user_id, current.id)
        elif status is FieldStatus.PENDING:
            pending = self.store.field_by_key(profile.id, key, FieldStatus.PENDING)
            if pending is not None:
                pending.value = value
                pending.evidence = evidence
                pending.confidence = confidence
                pending.source = source
                pending.updated_at = created
                self.store.upsert_field(pending)
                return pending
        item = ProfileField(
            id=new_id(),
            profile_id=profile.id,
            user_id=user_id,
            key=key,
            value=value,
            source=source,
            confidence=confidence,
            status=status,
            evidence=evidence,
            created_at=created,
            updated_at=created,
        )
        self.store.upsert_field(item)
        if status is FieldStatus.ACTIVE:
            self._bump(profile)
        return item

    def delete_field(self, user_id: UUID, key: str) -> None:
        profile = self.store.active_profile(user_id)
        if profile is None:
            raise NotFound("Profile not found.")
        key = normalize_key(key)
        item = self.store.field_by_key(profile.id, key, FieldStatus.ACTIVE)
        if item is None:
            raise NotFound("Field not found.")
        self.store.delete_field(user_id, item.id)
        self._bump(profile)

    def confirm(
        self,
        user_id: UUID,
        field_id: UUID,
        *,
        action: str,
        value: Any | None = None,
    ) -> ProfileField:
        item = self.store.get_field(user_id, field_id)
        if item is None:
            raise NotFound("Field not found.")
        if item.status is not FieldStatus.PENDING:
            raise InvalidRequest("Only pending fields can be confirmed.")
        profile = self.store.get_profile(user_id, item.profile_id)
        if profile is None or profile.archived_at is not None:
            raise NotFound("Profile not found.")
        if action == "reject":
            item.status = FieldStatus.REJECTED
            item.updated_at = now()
            return self.store.upsert_field(item)
        if action not in {"accept", "edit"}:
            raise InvalidRequest("action must be accept, reject, or edit.")
        if action == "edit":
            if value is None:
                raise InvalidRequest("value is required when editing.")
            item.value = _coerce(item.key, clamp_value(value))
            item.source = FieldSource.MANUAL
        current = self.store.field_by_key(profile.id, item.key, FieldStatus.ACTIVE)
        if current is not None and current.id != item.id:
            self.store.delete_field(user_id, current.id)
        item.status = FieldStatus.ACTIVE
        item.updated_at = now()
        self.store.upsert_field(item)
        self._bump(profile)
        return item

    def propose(self, user_id: UUID, drafts: list[ProfileDraft]) -> list[ProfileField]:
        """extracted drafts always land pending. Never skip this (PF-4)."""
        created: list[ProfileField] = []
        for draft in drafts[:5]:
            item = self.upsert_field(
                user_id,
                draft.key,
                draft.value,
                source=FieldSource.EXTRACTED,
                status=FieldStatus.PENDING,
                evidence=draft.evidence,
                confidence=draft.confidence,
            )
            created.append(item)
        return created

    def render_card(
        self,
        user_id: UUID,
        max_tokens: int = CARD_TOKEN_BUDGET,
        *,
        locale: str | None = None,
        fallback: str | None = None,
    ) -> str:
        profile = self.store.active_profile(user_id)
        if profile is None or profile.archived_at is not None:
            return ""
        settings = get_settings()
        locale = locale or settings.default_locale
        fallback = fallback or settings.fallback_locale
        cache_key = f"profile:{user_id}:v{profile.version}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        fields = [
            item
            for item in self.store.list_fields(profile.id, status=FieldStatus.ACTIVE)
            # extracted must be confirmed before it can be active; this is belt-and-braces
            if item.source is not FieldSource.EXTRACTED or item.status is FieldStatus.ACTIVE
        ]
        fields.sort(key=lambda item: (-INJECT_WEIGHT.get(item.key, 0), item.key))
        lines = ["<user_profile>"]
        used = estimate_tokens(lines[0])
        for item in fields:
            label = (
                pick_locale(self._bank.card_labels.get(item.key, {}), locale, fallback) or item.key
            )
            rendered = _render_value(item.value)
            if not rendered:
                continue
            line = f"{label}: {rendered}"
            cost = estimate_tokens(line)
            if used + cost > max_tokens:
                break
            lines.append(line)
            used += cost
        lines.append("</user_profile>")
        if len(lines) == 2:
            return ""
        card = "\n".join(lines)
        self._cache_set(cache_key, card)
        return card

    def export(self, user_id: UUID) -> dict[str, Any]:
        profiles = self.store.list_profiles(user_id, include_archived=True)
        out = []
        for profile in profiles:
            out.append(
                {
                    **profile_out(profile),
                    "fields": [field_out(item) for item in self.store.list_fields(profile.id)],
                }
            )
        return {"profiles": out}

    def purge(self, user_id: UUID) -> int:
        profile = self.store.active_profile(user_id)
        deleted = self.store.delete_profiles_for_user(user_id)
        if profile is not None:
            self._memory_cache.pop(f"profile:{user_id}:v{profile.version}", None)
        return deleted

    def archive(self, user_id: UUID, reason: str | None = None) -> Profile:
        profile = self.store.active_profile(user_id)
        if profile is None:
            raise NotFound("Profile not found.")
        profile.archived_at = now()
        profile.archive_reason = (reason or "").strip()[:200] or None
        profile.updated_at = now()
        self.store.upsert_profile(profile)
        self._memory_cache.pop(f"profile:{user_id}:v{profile.version}", None)
        return self.ensure_active(user_id)

    def start_interview(self, user_id: UUID) -> dict[str, Any]:
        profile = self.ensure_active(user_id)
        session = self.store.open_session(profile.id)
        if session is None:
            created = now()
            first = self._next_question({}, 1)
            session = InterviewSession(
                id=new_id(),
                user_id=user_id,
                profile_id=profile.id,
                status=InterviewStatus.IN_PROGRESS,
                round=first.round if first else 1,
                question_key=first.key if first else None,
                answers={},
                created_at=created,
                updated_at=created,
            )
            self.store.upsert_session(session)
        return self._interview_view(session)

    def answer_interview(
        self,
        user_id: UUID,
        *,
        text: str | None = None,
        selected: list[str] | None = None,
    ) -> dict[str, Any]:
        profile = self.ensure_active(user_id)
        session = self.store.open_session(profile.id)
        if session is None:
            raise InvalidRequest("Start the interview first.")
        question = self._bank.get(session.question_key or "")
        if question is None:
            raise InvalidRequest("No current question.")
        payload = {"text": (text or "").strip(), "selected": selected or []}
        if not payload["text"] and not payload["selected"]:
            raise InvalidRequest("Write an answer or pick an option.")
        session.answers[question.key] = payload
        self._apply_interview_extract(user_id, question, payload)
        starts_task = question.starts_task
        task_message = payload["text"] if starts_task else None
        nxt = self._advance(session)
        session.updated_at = now()
        self.store.upsert_session(session)
        view = self._interview_view(session)
        if starts_task and task_message:
            view["create_task"] = {"message": task_message}
        if nxt is None and session.status is InterviewStatus.AWAITING_SUMMARY:
            view["summary"] = self.render_card(user_id)
        return view

    def skip_interview(self, user_id: UUID, *, scope: str = "all") -> dict[str, Any]:
        profile = self.ensure_active(user_id)
        session = self.store.open_session(profile.id)
        if session is None:
            created = now()
            session = InterviewSession(
                id=new_id(),
                user_id=user_id,
                profile_id=profile.id,
                status=InterviewStatus.SKIPPED,
                round=1,
                question_key=None,
                answers={},
                created_at=created,
                updated_at=created,
            )
            self.store.upsert_session(session)
            return self._interview_view(session)
        if scope == "all":
            session.status = InterviewStatus.SKIPPED
            session.question_key = None
            session.updated_at = now()
            self.store.upsert_session(session)
            return self._interview_view(session)
        if scope == "round":
            current_round = session.round
            nxt = self._next_question(session.answers, current_round + 1)
            if nxt is None:
                session.status = InterviewStatus.AWAITING_SUMMARY
                session.question_key = None
            else:
                session.round = nxt.round
                session.question_key = nxt.key
            session.updated_at = now()
            self.store.upsert_session(session)
            return self._interview_view(session)
        if scope != "question":
            raise InvalidRequest("scope must be question, round, or all.")
        self._advance(session)
        session.updated_at = now()
        self.store.upsert_session(session)
        return self._interview_view(session)

    def complete_interview(self, user_id: UUID) -> dict[str, Any]:
        profile = self.ensure_active(user_id)
        session = self.store.open_session(profile.id)
        if session is None:
            raise InvalidRequest("No interview in progress.")
        session.status = InterviewStatus.COMPLETED
        session.updated_at = now()
        self.store.upsert_session(session)
        if not profile.completed:
            profile.completed = True
            self._bump(profile)
        return self._interview_view(session)

    def _advance(self, session: InterviewSession) -> InterviewQuestion | None:
        nxt = self._next_question(session.answers, session.round, after=session.question_key)
        if nxt is None:
            nxt = self._next_question(session.answers, session.round + 1)
        if nxt is None:
            session.status = InterviewStatus.AWAITING_SUMMARY
            session.question_key = None
            return None
        session.round = nxt.round
        session.question_key = nxt.key
        return nxt

    def _next_question(
        self,
        answers: dict[str, Any],
        round_no: int,
        after: str | None = None,
    ) -> InterviewQuestion | None:
        def eligible(question: InterviewQuestion) -> bool:
            if question.key in answers:
                return False
            if question.round == 3 and not should_ask(question, answers):
                return False
            return True

        if after is None:
            for question in self._bank.questions:
                if question.round == round_no and eligible(question):
                    return question
            for question in self._bank.questions:
                if question.round > round_no and eligible(question):
                    return question
            return None
        seen = False
        for question in self._bank.questions:
            if question.key == after:
                seen = True
                continue
            if not seen:
                continue
            if eligible(question):
                return question
        return None

    def _apply_interview_extract(
        self, user_id: UUID, question: InterviewQuestion, payload: dict[str, Any]
    ) -> None:
        values = _extract_from_answer(question, payload)
        for key, value in values.items():
            try:
                self.upsert_field(
                    user_id,
                    key,
                    value,
                    source=FieldSource.INTERVIEW,
                    status=FieldStatus.ACTIVE,
                    evidence={"question": question.key},
                )
            except InvalidRequest:
                continue

    def _interview_view(self, session: InterviewSession) -> dict[str, Any]:
        settings = get_settings()
        locale = settings.default_locale
        fallback = settings.fallback_locale
        question = self._bank.get(session.question_key or "")
        payload: dict[str, Any] = {
            "session": session_out(session),
            "question": None,
            "learned": [
                field_out(item)
                for item in self.store.list_fields(session.profile_id, status=FieldStatus.ACTIVE)
            ],
        }
        if question is not None:
            payload["question"] = {
                "key": question.key,
                "round": question.round,
                "required": question.required,
                "prompt": pick_locale(question.prompt, locale, fallback),
                "options": [
                    {
                        "id": opt.id,
                        "label": pick_locale(opt.labels, locale, fallback),
                    }
                    for opt in question.options
                ],
                "starts_task": question.starts_task,
            }
        return payload

    def _bump(self, profile: Profile) -> None:
        old_key = f"profile:{profile.user_id}:v{profile.version}"
        self._memory_cache.pop(old_key, None)
        profile.version += 1
        profile.updated_at = now()
        self.store.upsert_profile(profile)

    def _cache_get(self, key: str) -> str | None:
        if key in self._memory_cache:
            return self._memory_cache[key]
        if self._redis is None:
            return None
        try:
            raw = self._redis.get(key)
        except Exception:
            return None
        if raw is None:
            return None
        text = raw.decode() if isinstance(raw, bytes) else str(raw)
        self._memory_cache[key] = text
        return text

    def _cache_set(self, key: str, value: str) -> None:
        self._memory_cache[key] = value
        if self._redis is None:
            return
        try:
            self._redis.setex(key, CACHE_TTL_SECONDS, value)
        except Exception:
            return


def profile_out(profile: Profile) -> dict[str, Any]:
    return {
        "id": str(profile.id),
        "user_id": str(profile.user_id),
        "version": profile.version,
        "completed": profile.completed,
        "archived_at": profile.archived_at.isoformat() if profile.archived_at else None,
        "archive_reason": profile.archive_reason,
        "created_at": profile.created_at.isoformat(),
        "updated_at": profile.updated_at.isoformat(),
    }


def field_out(item: ProfileField) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "profile_id": str(item.profile_id),
        "key": item.key,
        "value": item.value,
        "source": item.source.value,
        "confidence": item.confidence,
        "status": item.status.value,
        "evidence": item.evidence,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def session_out(session: InterviewSession) -> dict[str, Any]:
    return {
        "id": str(session.id),
        "status": session.status.value,
        "round": session.round,
        "question_key": session.question_key,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }


def _coerce(key: str, value: Any) -> Any:
    if key in ARRAY_KEYS or key.startswith("custom."):
        if isinstance(value, str):
            parts = [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]
            return parts or [value]
        if isinstance(value, list):
            return value
    return value


def _render_value(value: Any) -> str:
    if isinstance(value, list):
        return "；".join(str(item) for item in value if str(item).strip())
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in value.items())
    return str(value).strip()


def _extract_from_answer(question: InterviewQuestion, payload: dict[str, Any]) -> dict[str, Any]:
    selected = payload.get("selected") or []
    text = str(payload.get("text") or "").strip()
    labels = []
    for opt in question.options:
        if opt.id in selected:
            labels.append(next(iter(opt.labels.values()), opt.id))
    blob = ", ".join(labels)
    if text:
        blob = f"{blob}; {text}" if blob else text
    out: dict[str, Any] = {}
    if question.key == "role":
        out["role"] = labels[0] if labels else text
        if selected:
            out["custom.sub_function"] = selected
    elif question.key == "company":
        parts = [p.strip() for p in text.replace(";", ",").split(",") if p.strip()]
        if parts:
            out["industry"] = parts[0]
            if len(parts) > 1:
                out["company_context"] = parts[1:]
            else:
                out["company_context"] = [text]
        elif text:
            out["company_context"] = [text]
    elif question.key == "first_task":
        if text:
            out["business_goals"] = [text]
    elif question.key in {"recurring_deliverables", "tools"}:
        out[question.key] = labels or ([text] if text else [])
    elif question.key == "output_format":
        out["preferences.output_format"] = labels[0] if labels else text
    elif question.key == "writing_tone":
        out["preferences.writing_tone"] = selected[0] if selected else text
    elif question.key == "followup_metric":
        if blob:
            out["business_goals"] = [blob]
    elif question.key == "followup_customer":
        if blob:
            out["company_context"] = [blob]
    elif question.key == "followup_report":
        if blob:
            out["custom.report_outline"] = [blob]
    return {k: v for k, v in out.items() if v not in ("", [], None)}
