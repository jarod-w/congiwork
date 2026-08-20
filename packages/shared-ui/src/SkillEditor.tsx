import type { Copy } from './types';

export interface SkillStepView {
  id: string;
  type: string;
  title: string;
  tool?: string | null;
  instruction?: string;
  fields?: string[];
  needs_clarification?: boolean;
  on_error?: string;
}

export interface SkillView {
  id: string;
  name: string;
  description: string;
  trigger: { type: string; patterns?: string[] };
  input_schema: {
    type?: string;
    properties?: Record<string, { title?: string; type?: string; enum?: string[] }>;
    required?: string[];
  };
  workflow: SkillStepView[];
  tools: string[];
  required_scopes: string[];
  source: string;
  status: string;
  version: number;
  run_count: number;
  success_count: number;
  success_rate: number | null;
}

export interface PresetView {
  id: string;
  name: string;
  description: string;
  workflow: SkillStepView[];
  required_scopes: string[];
}

interface LibraryProps {
  copy: Copy;
  skills: SkillView[];
  presets: PresetView[];
  onOpen: (id: string) => void;
  onCopyPreset: (id: string) => void;
  onNew: () => void;
}

export function SkillLibrary({ copy, skills, presets, onOpen, onCopyPreset, onNew }: LibraryProps) {
  return (
    <div className="cw-memory">
      <header className="cw-memory-head">
        <div>
          <h1>{copy.skills}</h1>
          <p className="cw-muted">{copy.skillHint}</p>
        </div>
        <button type="button" className="cw-btn cw-btn-primary" onClick={onNew}>
          {copy.newSkill}
        </button>
      </header>
      <ul className="cw-memory-list">
        {skills.map((skill) => (
          <li key={skill.id} className="cw-memory-card">
            <button type="button" className="cw-task" onClick={() => onOpen(skill.id)}>
              <strong>{skill.name}</strong>
              <small>
                {skill.status} · {copy.usedNTimes.replace('{n}', String(skill.run_count))}
              </small>
              <p className="cw-muted">{skill.description}</p>
            </button>
          </li>
        ))}
      </ul>
      <h2>{copy.presets}</h2>
      <ul className="cw-memory-list">
        {presets.map((preset) => (
          <li key={preset.id} className="cw-memory-card">
            <strong>{preset.name}</strong>
            <p className="cw-muted">{preset.description}</p>
            <button type="button" className="cw-btn" onClick={() => onCopyPreset(preset.id)}>
              {copy.useThis}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

interface EditorProps {
  copy: Copy;
  skill: SkillView;
  missingScopes: string[];
  unresolved: { step_id: string; title: string; candidates: string[] }[];
  onChange: (skill: SkillView) => void;
  onSave: () => void;
  onRun: (dryRun: boolean) => void;
  onActivate: () => void;
}

export function SkillEditor({
  copy,
  skill,
  missingScopes,
  unresolved,
  onChange,
  onSave,
  onRun,
  onActivate,
}: EditorProps) {
  const properties = skill.input_schema.properties || {};
  return (
    <div className="cw-memory">
      <header className="cw-memory-head">
        <div>
          <input
            className="cw-remember input"
            value={skill.name}
            onChange={(event) => onChange({ ...skill, name: event.target.value })}
          />
          <textarea
            value={skill.description}
            onChange={(event) => onChange({ ...skill, description: event.target.value })}
          />
        </div>
        <div className="cw-row">
          <button type="button" className="cw-btn" onClick={() => onRun(true)}>
            {copy.dryRun}
          </button>
          <button type="button" className="cw-btn cw-btn-primary" onClick={onSave}>
            {copy.saveSkill}
          </button>
        </div>
      </header>
      <section>
        <h2>{copy.parameters}</h2>
        {Object.keys(properties).length ? (
          <ul>
            {Object.entries(properties).map(([key, spec]) => (
              <li key={key}>{spec.title || key}</li>
            ))}
          </ul>
        ) : (
          <p className="cw-muted">{copy.noneYet}</p>
        )}
      </section>
      <section>
        <h2>{copy.steps}</h2>
        <ol className="cw-skill-steps">
          {skill.workflow.map((step, index) => (
            <li key={step.id} className="cw-memory-card">
              <div className="cw-step-title">{step.title}</div>
              <p className="cw-muted">
                {step.type}
                {step.type === 'tool' ? ` · ${step.tool || copy.toolUnset}` : ''}
                {step.needs_clarification ? ` · ${copy.needsClarification}` : ''}
              </p>
              <div className="cw-row">
                <button
                  type="button"
                  className="cw-btn cw-btn-ghost"
                  onClick={() => {
                    if (index === 0) return;
                    const workflow = [...skill.workflow];
                    [workflow[index - 1], workflow[index]] = [workflow[index], workflow[index - 1]];
                    onChange({ ...skill, workflow });
                  }}
                >
                  ↑
                </button>
                <button
                  type="button"
                  className="cw-btn cw-btn-ghost"
                  onClick={() =>
                    onChange({
                      ...skill,
                      workflow: skill.workflow.filter((item) => item.id !== step.id),
                    })
                  }
                >
                  {copy.delete}
                </button>
              </div>
            </li>
          ))}
        </ol>
        <button
          type="button"
          className="cw-btn"
          onClick={() =>
            onChange({
              ...skill,
              workflow: [
                ...skill.workflow,
                {
                  id: `s${skill.workflow.length + 1}`,
                  type: 'llm',
                  title: copy.newStep,
                  instruction: '',
                },
              ],
            })
          }
        >
          {copy.addStep}
        </button>
      </section>
      <section>
        <h2>{copy.neededPermissions}</h2>
        {skill.required_scopes.length ? (
          <ul>
            {skill.required_scopes.map((scope) => (
              <li key={scope}>
                {scope}
                {missingScopes.includes(scope) ? ` · ${copy.notConnected}` : ' ✓'}
              </li>
            ))}
          </ul>
        ) : (
          <p className="cw-muted">{copy.noneYet}</p>
        )}
        {unresolved.length ? (
          <p className="cw-muted">
            {copy.toolUnset}: {unresolved.map((item) => item.title).join(', ')}
          </p>
        ) : null}
      </section>
      {skill.status === 'draft' ? (
        <button type="button" className="cw-btn cw-btn-primary" onClick={onActivate}>
          {copy.activateSkill}
        </button>
      ) : (
        <button type="button" className="cw-btn cw-btn-primary" onClick={() => onRun(false)}>
          {copy.runSkill}
        </button>
      )}
    </div>
  );
}
