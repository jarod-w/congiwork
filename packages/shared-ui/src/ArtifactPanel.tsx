import type { ArtifactItem, ArtifactPreview, Copy } from './types';

interface Props {
  copy: Copy;
  artifacts: ArtifactItem[];
  onDownload: (id: string, filename: string) => void;
  /** WS-5：展开预览。解析在后端（runtime/preview.py），这里只渲染四种 kind。 */
  onPreview?: (id: string) => void;
  previews?: Record<string, ArtifactPreview | undefined>;
  openId?: string | null;
}

export function ArtifactPanel({
  copy,
  artifacts,
  onDownload,
  onPreview,
  previews,
  openId,
}: Props) {
  return (
    <section className="cw-artifacts">
      <h2>{copy.artifacts}</h2>
      {artifacts.length === 0 ? <p className="cw-muted">{copy.noneYet}</p> : null}
      <ul>
        {artifacts.map((item) => {
          const open = openId === item.id;
          return (
            <li key={item.id}>
              <div className="cw-artifact-row">
                <span>{item.filename}</span>
                <span className="cw-artifact-actions">
                  {onPreview ? (
                    <button
                      type="button"
                      className="cw-btn cw-btn-ghost"
                      aria-expanded={open}
                      onClick={() => onPreview(item.id)}
                    >
                      {open ? copy.collapse : copy.preview}
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="cw-btn cw-btn-ghost"
                    onClick={() => onDownload(item.id, item.filename)}
                  >
                    {copy.download}
                  </button>
                </span>
              </div>
              {open ? <Preview copy={copy} preview={previews?.[item.id]} /> : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Preview({ copy, preview }: { copy: Copy; preview?: ArtifactPreview }) {
  if (!preview) return <p className="cw-muted">{copy.working}…</p>;
  if (preview.kind === 'none') return <p className="cw-muted">{copy.noPreview}</p>;
  if (preview.kind === 'image') {
    return (
      <div className="cw-preview">
        <img src={preview.data_uri} alt="" />
      </div>
    );
  }
  if (preview.kind === 'table') {
    return (
      <div className="cw-preview">
        {/* 宽表在自己的容器里横向滚动，不让整个面板跟着抖。 */}
        <div className="cw-preview-scroll">
          <table className="cw-preview-table">
            {preview.header?.length ? (
              <thead>
                <tr>
                  {preview.header.map((cell, index) => (
                    <th key={index}>{cell}</th>
                  ))}
                </tr>
              </thead>
            ) : null}
            <tbody>
              {(preview.rows ?? []).map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {preview.truncated ? (
          <p className="cw-muted">{copy.previewTruncated.replace('{n}', String(preview.row_count ?? 0))}</p>
        ) : null}
      </div>
    );
  }
  return (
    <div className="cw-preview">
      <pre className="cw-preview-text">{preview.text}</pre>
      {preview.truncated ? <p className="cw-muted">{copy.previewClipped}</p> : null}
    </div>
  );
}
