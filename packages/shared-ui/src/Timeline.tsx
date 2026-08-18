import type { Copy, StepItem } from './types';

interface Props {
  copy: Copy;
  steps: StepItem[];
}

export function Timeline({ copy, steps }: Props) {
  if (steps.length === 0) return null;
  return (
    <ol className="cw-timeline">
      {steps.map((step) => (
        <li key={step.id} className={`cw-step is-${step.status}`}>
          <span className="cw-step-mark" aria-hidden="true" />
          <div>
            <div className="cw-step-title">{step.title}</div>
            <div className="cw-step-meta">
              {step.type}
              {step.duration_ms != null ? ` · ${(step.duration_ms / 1000).toFixed(1)}s` : ''}
              {step.status === 'failed' ? ` · ${copy.failed}` : ''}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}
