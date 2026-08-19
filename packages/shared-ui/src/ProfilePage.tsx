import type { Copy } from './types';

export interface ProfileFieldView {
  id: string;
  key: string;
  value: unknown;
  source: string;
  status: string;
  evidence?: Record<string, unknown> | null;
}

export interface InterviewQuestionView {
  key: string;
  round: number;
  required: boolean;
  prompt: string;
  options: { id: string; label: string }[];
  starts_task: boolean;
}

interface Props {
  copy: Copy;
  fields: ProfileFieldView[];
  pending: ProfileFieldView[];
  question: InterviewQuestionView | null;
  learned: ProfileFieldView[];
  draft: string;
  selected: string[];
  completed: boolean;
  archivedCount: number;
  onDraft: (value: string) => void;
  onToggleOption: (id: string) => void;
  onAnswer: () => void;
  onSkipQuestion: () => void;
  onSkipAll: () => void;
  onStart: () => void;
  onComplete: () => void;
  onConfirmPending: (id: string, accept: boolean) => void;
  onDeleteField: (key: string) => void;
  onArchive: () => void;
}

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(String).join(', ');
  if (value && typeof value === 'object') return JSON.stringify(value);
  return String(value ?? '');
}

export function ProfilePage({
  copy,
  fields,
  pending,
  question,
  learned,
  draft,
  selected,
  completed,
  archivedCount,
  onDraft,
  onToggleOption,
  onAnswer,
  onSkipQuestion,
  onSkipAll,
  onStart,
  onComplete,
  onConfirmPending,
  onDeleteField,
  onArchive,
}: Props) {
  const active = fields.filter((item) => item.status === 'active');
  return (
    <div className="cw-memory">
      <header className="cw-memory-head">
        <div>
          <h1>{copy.profile}</h1>
          <p className="cw-muted">{copy.profileHint}</p>
        </div>
        <button type="button" className="cw-btn cw-btn-ghost" onClick={onArchive}>
          {copy.changeJob}
        </button>
      </header>

      {question ? (
        <section className="cw-interview">
          <p className="cw-muted">
            Round {question.round}
            {question.required ? '' : ` · ${copy.skipThis}`}
          </p>
          <h2>{question.prompt}</h2>
          <div className="cw-row cw-wrap">
            {question.options.map((opt) => (
              <button
                key={opt.id}
                type="button"
                className={selected.includes(opt.id) ? 'cw-btn cw-btn-primary' : 'cw-btn'}
                onClick={() => onToggleOption(opt.id)}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <textarea
            value={draft}
            onChange={(event) => onDraft(event.target.value)}
            rows={3}
            placeholder={copy.composerPlaceholder}
          />
          <div className="cw-row cw-row-equal">
            <button type="button" className="cw-btn cw-btn-primary" onClick={onAnswer}>
              {copy.continueInterview}
            </button>
            <button type="button" className="cw-btn" onClick={question.required ? onSkipAll : onSkipQuestion}>
              {question.required ? copy.skipSetup : copy.skipThis}
            </button>
          </div>
          <div className="cw-row">
            <button type="button" className="cw-btn cw-btn-ghost" onClick={onSkipAll}>
              {copy.skipSetup}
            </button>
          </div>
        </section>
      ) : (
        <div className="cw-row">
          {!completed ? (
            <button type="button" className="cw-btn cw-btn-primary" onClick={onStart}>
              {copy.continueInterview}
            </button>
          ) : (
            <button type="button" className="cw-btn" onClick={onComplete}>
              {copy.confirmSummary}
            </button>
          )}
          <button type="button" className="cw-btn" onClick={onSkipAll}>
            {copy.skipSetup}
          </button>
        </div>
      )}

      <section>
        <h2>{copy.learned}</h2>
        {learned.length === 0 && active.length === 0 ? <p className="cw-muted">{copy.noneYet}</p> : null}
        <ul className="cw-memory-list">
          {active.map((item) => (
            <li key={item.id} className="cw-memory-card">
              <strong>{item.key}</strong>
              <p>{formatValue(item.value)}</p>
              <p className="cw-muted">{item.source}</p>
              <button type="button" className="cw-btn cw-btn-ghost" onClick={() => onDeleteField(item.key)}>
                {copy.delete}
              </button>
            </li>
          ))}
        </ul>
      </section>

      {pending.length ? (
        <section>
          <h2>{copy.pending}</h2>
          <ul className="cw-memory-list">
            {pending.map((item) => (
              <li key={item.id} className="cw-memory-card">
                <strong>{item.key}</strong>
                <p>{formatValue(item.value)}</p>
                <div className="cw-row">
                  <button type="button" className="cw-btn cw-btn-primary" onClick={() => onConfirmPending(item.id, true)}>
                    {copy.confirm}
                  </button>
                  <button type="button" className="cw-btn" onClick={() => onConfirmPending(item.id, false)}>
                    {copy.reject}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {archivedCount ? <p className="cw-muted">{copy.archiveHint}</p> : null}
    </div>
  );
}
