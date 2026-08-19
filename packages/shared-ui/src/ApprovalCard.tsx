import { useState } from 'react';
import type { ApprovalCardData, Copy } from './types';

interface Props {
  copy: Copy;
  approval: ApprovalCardData;
  onResolve: (action: string, edited?: Record<string, unknown>) => void;
}

export function ApprovalCard({ copy, approval, onResolve }: Props) {
  const preview = approval.preview;
  const [body, setBody] = useState(String(preview.data.body ?? preview.data.after ?? preview.data.summary ?? ''));
  const irreversible = approval.risk === 'irreversible';
  return (
    <article className="cw-approval">
      <header>
        <strong>{copy.needsConfirmation}</strong>
        <p>{approval.title}</p>
      </header>
      {preview.type === 'email' ? (
        <div className="cw-preview">
          <p>To: {String((preview.data.to_count as number) ?? (preview.data.to as string[])?.length ?? '')}</p>
          <p>Subject: {String(preview.data.subject ?? '')}</p>
          <textarea value={body} onChange={(event) => setBody(event.target.value)} rows={8} />
        </div>
      ) : null}
      {preview.type === 'table' ? (
        <p className="cw-muted">{String(preview.data.row_count ?? 0)} rows</p>
      ) : null}
      {preview.type === 'diff' ? (
        <div className="cw-preview">
          <pre>{String(preview.data.before ?? '')}</pre>
          <textarea value={body} onChange={(event) => setBody(event.target.value)} rows={6} />
        </div>
      ) : null}
      {preview.type === 'text' ? (
        <textarea value={body} onChange={(event) => setBody(event.target.value)} rows={6} />
      ) : null}
      <div className="cw-row cw-wrap">
        <button type="button" className="cw-btn cw-btn-primary" onClick={() => onResolve('approve')}>
          {copy.approve}
        </button>
        <button
          type="button"
          className="cw-btn"
          onClick={() => onResolve('edit_and_approve', { body })}
        >
          {copy.editAndApprove}
        </button>
        <button type="button" className="cw-btn" onClick={() => onResolve('skip')}>
          {copy.skipStep}
        </button>
        <button type="button" className="cw-btn cw-btn-ghost" onClick={() => onResolve('reject')}>
          {copy.cancelTask}
        </button>
      </div>
      {irreversible ? null : (
        <label className="cw-muted">
          <input
            type="checkbox"
            onChange={(event) => {
              if (event.target.checked) onResolve('always_allow_this_scope');
            }}
          />{' '}
          {copy.alwaysAllowThis}
        </label>
      )}
    </article>
  );
}
