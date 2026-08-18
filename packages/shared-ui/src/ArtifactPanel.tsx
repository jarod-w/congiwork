import type { ArtifactItem, Copy } from './types';

interface Props {
  copy: Copy;
  artifacts: ArtifactItem[];
  onDownload: (id: string, filename: string) => void;
}

export function ArtifactPanel({ copy, artifacts, onDownload }: Props) {
  return (
    <section className="cw-artifacts">
      <h2>{copy.artifacts}</h2>
      {artifacts.length === 0 ? <p className="cw-muted">{copy.noneYet}</p> : null}
      <ul>
        {artifacts.map((item) => (
          <li key={item.id}>
            <span>{item.filename}</span>
            <button type="button" className="cw-btn cw-btn-ghost" onClick={() => onDownload(item.id, item.filename)}>
              {copy.download}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
