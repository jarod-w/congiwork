import type { Copy, ScopeCard } from './types';

interface Props {
  copy: Copy;
  scope: ScopeCard;
  onEnable: () => void;
  onSkip: () => void;
}

export function ConsentCard({ copy, scope, onEnable, onSkip }: Props) {
  // Four sections are mandatory (P0-07 §6.1). Buttons share visual weight —
  // "Not now" must not look like a grey afterthought.
  return (
    <article className="cw-consent">
      <h2>{scope.copy.display_name}</h2>
      <section>
        <h3>{copy.whatThisDoes}</h3>
        <p>{scope.copy.collects}</p>
      </section>
      <section>
        <h3>{copy.whatWeWillNotDo}</h3>
        <p>{copy.willNotBody}</p>
      </section>
      <section>
        <h3>{copy.whatWeKeep}</h3>
        <p>{scope.copy.retention}</p>
      </section>
      <section>
        <h3>{copy.ifYouSkip}</h3>
        <p>{scope.copy.degraded_behavior}</p>
      </section>
      <div className="cw-row cw-row-equal">
        <button type="button" className="cw-btn" onClick={onEnable}>
          {copy.enable}
        </button>
        <button type="button" className="cw-btn" onClick={onSkip}>
          {copy.notNow}
        </button>
      </div>
    </article>
  );
}
