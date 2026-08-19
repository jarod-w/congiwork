import type { Copy, MemoryItem } from './types';

interface Props {
  copy: Copy;
  items: MemoryItem[];
  onKeep: () => void;
  onSkip: () => void;
}

export function CaptureCard({ copy, items, onKeep, onSkip }: Props) {
  if (items.length === 0) return null;
  return (
    <article className="cw-capture">
      <h2>{copy.captureTitle}</h2>
      <ul>
        {items.slice(0, 3).map((item) => (
          <li key={item.id}>{item.summary || item.content}</li>
        ))}
      </ul>
      <div className="cw-row">
        <button type="button" className="cw-btn cw-btn-primary" onClick={onKeep}>
          {copy.captureKeep}
        </button>
        <button type="button" className="cw-btn" onClick={onSkip}>
          {copy.captureSkip}
        </button>
      </div>
    </article>
  );
}
