import type { Copy, MemoryItem } from './types';

interface Props {
  copy: Copy;
  items: MemoryItem[];
  profileItems?: { id: string; key: string; value: unknown }[];
  onKeep: () => void;
  onSkip: () => void;
}

export function CaptureCard({ copy, items, profileItems = [], onKeep, onSkip }: Props) {
  if (items.length === 0 && profileItems.length === 0) return null;
  return (
    <article className="cw-capture">
      <h2>{copy.captureTitle}</h2>
      <ul>
        {items.slice(0, 3).map((item) => (
          <li key={item.id}>{item.summary || item.content}</li>
        ))}
        {profileItems.slice(0, 3).map((item) => (
          <li key={item.id}>
            {item.key}: {Array.isArray(item.value) ? item.value.join(', ') : String(item.value)}
          </li>
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
