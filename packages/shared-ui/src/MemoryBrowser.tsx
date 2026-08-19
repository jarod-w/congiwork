import type { Copy, MemoryItem } from './types';

interface Props {
  copy: Copy;
  items: MemoryItem[];
  pending: MemoryItem[];
  tab: 'semantic' | 'preference' | 'episodic' | 'pending';
  draft: string;
  onTab: (tab: 'semantic' | 'preference' | 'episodic' | 'pending') => void;
  onDraft: (value: string) => void;
  onRemember: () => void;
  onConfirm: (id: string, accept: boolean) => void;
  onDelete: (id: string) => void;
  onDeleteAll: () => void;
}

export function MemoryBrowser({
  copy,
  items,
  pending,
  tab,
  draft,
  onTab,
  onDraft,
  onRemember,
  onConfirm,
  onDelete,
  onDeleteAll,
}: Props) {
  const visible = tab === 'pending' ? pending : items;
  return (
    <div className="cw-memory">
      <header className="cw-memory-head">
        <div>
          <h1>{copy.memory}</h1>
          <p className="cw-muted">{copy.emptyMemory}</p>
        </div>
        <button type="button" className="cw-btn cw-btn-ghost" onClick={onDeleteAll}>
          {copy.deleteAll}
        </button>
      </header>
      <nav className="cw-tabs">
        {(
          [
            ['semantic', copy.facts],
            ['preference', copy.preferences],
            ['episodic', copy.history],
            ['pending', `${copy.pending}${pending.length ? ` (${pending.length})` : ''}`],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={tab === key ? 'cw-tab is-active' : 'cw-tab'}
            onClick={() => onTab(key)}
          >
            {label}
          </button>
        ))}
      </nav>
      <form
        className="cw-remember"
        onSubmit={(event) => {
          event.preventDefault();
          onRemember();
        }}
      >
        <input
          value={draft}
          onChange={(event) => onDraft(event.target.value)}
          placeholder={copy.rememberHint}
        />
        <button type="submit" className="cw-btn cw-btn-primary" disabled={!draft.trim()}>
          {copy.remember}
        </button>
      </form>
      {visible.length === 0 ? <p className="cw-muted">{copy.noneYet}</p> : null}
      <ul className="cw-memory-list">
        {visible.map((item) => (
          <li key={item.id} className="cw-memory-card">
            <strong>{item.summary || item.content}</strong>
            <p>{item.content}</p>
            <p className="cw-muted">
              {item.source_type}
              {item.source_ref && typeof item.source_ref.quote === 'string'
                ? ` · ${copy.whyThis}: ${item.source_ref.quote}`
                : ''}
              {` · ${copy.usedNTimes.replace('{n}', String(item.use_count))}`}
            </p>
            {item.conflict_with ? <p className="cw-error">{copy.needsConfirmation}</p> : null}
            <div className="cw-row">
              {item.status === 'pending' ? (
                <>
                  <button type="button" className="cw-btn cw-btn-primary" onClick={() => onConfirm(item.id, true)}>
                    {copy.confirm}
                  </button>
                  <button type="button" className="cw-btn" onClick={() => onConfirm(item.id, false)}>
                    {copy.reject}
                  </button>
                </>
              ) : (
                <button type="button" className="cw-btn cw-btn-ghost" onClick={() => onDelete(item.id)}>
                  {copy.delete}
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
