import type { Copy } from './types';

interface Grant {
  scope_key: string;
  action: string;
  display_name: string;
  trust_level: string | null;
  risk: string | null;
}

interface Activity {
  id: string;
  summary: string;
  created_at: string;
  task_id?: string | null;
}

interface Props {
  copy: Copy;
  grants: Grant[];
  activity: Activity[];
  data: { memories: number; tasks: number; files: number };
  markets: string;
  cleanup: boolean;
  onCleanup: (value: boolean) => void;
  onRevoke: (scope: string) => void;
  onExport: () => void;
  onDeleteAccount: () => void;
}

export function PrivacyCenter({
  copy,
  grants,
  activity,
  data,
  markets,
  cleanup,
  onCleanup,
  onRevoke,
  onExport,
  onDeleteAccount,
}: Props) {
  return (
    <div className="cw-privacy">
      <h1>{copy.privacy}</h1>
      {/*
        P0-07 §10 的三条边界，标题就是「必须在产品内明示」。三条都要在，不是
        「其中一条」：管理员那条决定用户理解的是「我可以拒绝」还是「公司会替我开」，
        合规那条防的是把可审计记录误当成合规结论。
      */}
      <ul className="cw-boundaries">
        <li className="cw-muted">{copy.adminBoundary}</li>
        <li className="cw-muted">{markets}</li>
        <li className="cw-muted">{copy.complianceBoundary}</li>
      </ul>
      <section>
        <h2>{copy.authorizations}</h2>
        {grants.length === 0 ? <p className="cw-muted">{copy.noneYet}</p> : null}
        <ul className="cw-memory-list">
          {grants.map((grant) => (
            <li key={grant.scope_key} className="cw-memory-card">
              <strong>{grant.display_name}</strong>
              <p className="cw-muted">
                {grant.scope_key} · {grant.action} · {grant.trust_level} · {grant.risk}
              </p>
              {grant.action === 'granted' ? (
                <button type="button" className="cw-btn" onClick={() => onRevoke(grant.scope_key)}>
                  {copy.notNow}
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h2>{copy.activity}</h2>
        {activity.length === 0 ? <p className="cw-muted">{copy.noneYet}</p> : null}
        <ul>
          {activity.map((row) => (
            <li key={row.id}>
              <span>{row.summary}</span>
              <small className="cw-muted"> {row.created_at}</small>
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h2>{copy.myData}</h2>
        <p>
          {copy.memories}: {data.memories} · {copy.tasks}: {data.tasks} · {copy.files}: {data.files}
        </p>
        <label>
          <input type="checkbox" checked={cleanup} onChange={(event) => onCleanup(event.target.checked)} /> {copy.cleanupLabel}
        </label>
        <p className="cw-muted">{copy.cleanupHint}</p>
        <div className="cw-row">
          <button type="button" className="cw-btn" onClick={onExport}>
            {copy.exportAll}
          </button>
          <button type="button" className="cw-btn cw-btn-ghost" onClick={onDeleteAccount}>
            {copy.deleteAccount}
          </button>
        </div>
      </section>
    </div>
  );
}
