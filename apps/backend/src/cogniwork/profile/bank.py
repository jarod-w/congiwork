"""Load the interview question bank. Locale comes from settings, not literals."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import yaml

from cogniwork.core.paths import find_config_file


@dataclass(frozen=True, slots=True)
class QuestionOption:
    id: str
    labels: dict[str, str]


@dataclass(frozen=True, slots=True)
class FollowWhen:
    role_in: tuple[str, ...] = ()
    company_context: str | None = None
    recurring_deliverables: str | None = None


@dataclass(frozen=True, slots=True)
class InterviewQuestion:
    key: str
    round: int
    required: bool
    extracts: tuple[str, ...]
    prompt: dict[str, str]
    options: tuple[QuestionOption, ...] = ()
    starts_task: bool = False
    follow_up_when: FollowWhen = field(default_factory=FollowWhen)


@dataclass(frozen=True, slots=True)
class QuestionBank:
    questions: tuple[InterviewQuestion, ...]
    card_labels: dict[str, dict[str, str]]
    source_labels: dict[str, dict[str, str]]

    def for_round(self, round_no: int) -> list[InterviewQuestion]:
        return [q for q in self.questions if q.round == round_no]

    def get(self, key: str) -> InterviewQuestion | None:
        for question in self.questions:
            if question.key == key:
                return question
        return None


def pick_locale(mapping: dict[str, str], locale: str, fallback: str) -> str:
    if locale in mapping:
        return mapping[locale]
    if fallback in mapping:
        return mapping[fallback]
    return next(iter(mapping.values()), "")


@lru_cache(maxsize=1)
def load_bank() -> QuestionBank:
    path = find_config_file("interview_question.yaml", "COGNIWORK_INTERVIEW_PATH")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    questions: list[InterviewQuestion] = []
    for entry in raw.get("questions") or []:
        follow = entry.get("follow_up_when") or {}
        questions.append(
            InterviewQuestion(
                key=entry["key"],
                round=int(entry["round"]),
                required=bool(entry.get("required")),
                extracts=tuple(entry.get("extracts") or ()),
                prompt=dict(entry.get("prompt") or {}),
                options=tuple(
                    QuestionOption(id=opt["id"], labels=dict(opt.get("labels") or {}))
                    for opt in (entry.get("options") or [])
                ),
                starts_task=bool(entry.get("starts_task")),
                follow_up_when=FollowWhen(
                    role_in=tuple(follow.get("role_in") or ()),
                    company_context=follow.get("company_context"),
                    recurring_deliverables=follow.get("recurring_deliverables"),
                ),
            )
        )
    return QuestionBank(
        questions=tuple(questions),
        card_labels={k: dict(v) for k, v in (raw.get("card_labels") or {}).items()},
        source_labels={k: dict(v) for k, v in (raw.get("source_labels") or {}).items()},
    )


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def should_ask(question: InterviewQuestion, answers: dict[str, Any]) -> bool:
    rule = question.follow_up_when
    if not rule.role_in and not rule.company_context and not rule.recurring_deliverables:
        return True
    if rule.role_in:
        role = _answer_ids(answers.get("role"))
        if not any(item in rule.role_in for item in role) and not _text_hit(
            answers.get("role"), rule.role_in
        ):
            return False
    if rule.company_context == "vague":
        blob = _flatten(answers.get("company"))
        if len(blob) >= 40:
            return False
    if rule.recurring_deliverables == "nonempty":
        if not _flatten(answers.get("recurring_deliverables")):
            return False
    return True


def _answer_ids(answer: Any) -> list[str]:
    if isinstance(answer, dict):
        selected = answer.get("selected") or []
        if isinstance(selected, str):
            return [selected]
        return [str(item) for item in selected]
    return []


def _flatten(answer: Any) -> str:
    if answer is None:
        return ""
    if isinstance(answer, str):
        return answer.strip()
    if isinstance(answer, dict):
        parts = [
            *(_answer_ids(answer)),
            str(answer.get("text") or ""),
        ]
        return " ".join(p for p in parts if p).strip()
    if isinstance(answer, list):
        return " ".join(str(item) for item in answer)
    return str(answer)


def _text_hit(answer: Any, needles: tuple[str, ...]) -> bool:
    blob = _flatten(answer).lower()
    return any(n.lower() in blob for n in needles)
