import type { ArtifactPreview, ContextBundle, Copy } from './types';
import { ArtifactPanel } from './ArtifactPanel';

interface Props {
  copy: Copy;
  bundle: ContextBundle | null;
  open: boolean;
  onToggle: () => void;
  onDownload: (id: string, filename: string) => void;
  onPreview?: (id: string) => void;
  previews?: Record<string, ArtifactPreview | undefined>;
  openArtifact?: string | null;
}

export function ContextPanel({
  copy,
  bundle,
  open,
  onToggle,
  onDownload,
  onPreview,
  previews,
  openArtifact,
}: Props) {
  return (
    <div className="cw-context">
      <header>
        <div>
          <h1>{copy.grounds}</h1>
          <p>{copy.groundsHint}</p>
        </div>
        <button type="button" className="cw-btn cw-btn-ghost" onClick={onToggle}>
          {open ? copy.collapse : copy.expand}
        </button>
      </header>
      {open ? (
        <>
          <section>
            <h2>{copy.profile}</h2>
            {bundle?.profile_card ? (
              <pre className="cw-muted">{bundle.profile_card}</pre>
            ) : (
              <p className="cw-muted">{copy.noneYet}</p>
            )}
          </section>
          <section>
            <h2>{copy.files}</h2>
            {bundle?.files.length ? (
              <ul>
                {bundle.files.map((file) => (
                  <li key={file.id}>{file.filename}</li>
                ))}
              </ul>
            ) : (
              <p className="cw-muted">{copy.noneYet}</p>
            )}
          </section>
          <section>
            <h2>{copy.toolsUsed}</h2>
            {bundle?.tools.length ? (
              <ul>
                {bundle.tools.map((tool) => (
                  <li key={tool}>{tool}</li>
                ))}
              </ul>
            ) : (
              <p className="cw-muted">{copy.noneYet}</p>
            )}
          </section>
          <section>
            <h2>{copy.memories}</h2>
            {bundle?.memories.length ? (
              <ul>
                {bundle.memories.map((memory) => (
                  <li key={memory.id}>
                    <strong>{memory.summary || memory.type}</strong>
                    <div className="cw-muted">{memory.content}</div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="cw-muted">{copy.noneYet}</p>
            )}
          </section>
          <section>
            <h2>{copy.skills}</h2>
            {bundle?.skills?.length ? (
              <ul>
                {bundle.skills.map((skill) => (
                  <li key={String(skill.id ?? skill.name)}>
                    {String(skill.name ?? copy.noneYet)}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="cw-muted">{copy.noneYet}</p>
            )}
          </section>
          <ArtifactPanel
            copy={copy}
            artifacts={bundle?.artifacts ?? []}
            onDownload={onDownload}
            onPreview={onPreview}
            previews={previews}
            openId={openArtifact}
          />
        </>
      ) : null}
    </div>
  );
}
