import type { Copy } from './types';

export interface TemplateView {
  id: string;
  title: string;
  prompt: string;
  needs_file: boolean;
}

interface Props {
  copy: Copy;
  templates: TemplateView[];
  onUse: (template: TemplateView) => void;
}

export function EmptyState({ copy, templates, onUse }: Props) {
  return (
    <div className="cw-empty">
      <p className="cw-muted">{copy.emptyTasks}</p>
      <ul className="cw-memory-list">
        {templates.map((template) => (
          <li key={template.id} className="cw-memory-card">
            <strong>{template.title}</strong>
            <p className="cw-muted">{template.prompt}</p>
            <button type="button" className="cw-btn cw-btn-primary" onClick={() => onUse(template)}>
              {copy.useThis}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
