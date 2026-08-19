import type { FormEvent } from 'react';
import type { Copy } from './types';

interface Props {
  copy: Copy;
  value: string;
  busy: boolean;
  fileName: string | null;
  saveToMemory: boolean;
  onChange: (value: string) => void;
  onFile: (file: File | null) => void;
  onSaveToMemory: (value: boolean) => void;
  onSubmit: () => void;
}

export function Composer({
  copy,
  value,
  busy,
  fileName,
  saveToMemory,
  onChange,
  onFile,
  onSaveToMemory,
  onSubmit,
}: Props) {
  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!busy) onSubmit();
  }
  return (
    <form className="cw-composer" onSubmit={handleSubmit}>
      <label className="cw-attach">
        <input
          type="file"
          accept=".xlsx,.csv,.txt,.md,.json,.pdf,.docx"
          onChange={(event) => onFile(event.target.files?.[0] ?? null)}
        />
        <span>{fileName || copy.attach}</span>
      </label>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={copy.composerPlaceholder}
        rows={3}
        disabled={busy}
      />
      <label className="cw-muted cw-persist">
        <input
          type="checkbox"
          checked={saveToMemory}
          onChange={(event) => onSaveToMemory(event.target.checked)}
          disabled={!fileName}
        />{' '}
        {copy.saveToMemory}
      </label>
      <button type="submit" className="cw-btn cw-btn-primary" disabled={busy || !value.trim()}>
        {copy.send}
      </button>
    </form>
  );
}
