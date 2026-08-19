import type { Copy } from './types';

export interface ProviderView {
  id: string;
  display_name: string;
  scopes: { key: string; display_name: string; risk: string }[];
}

export interface ConnectionView {
  id: string;
  provider: string;
  account_label: string | null;
  granted_scopes: string[];
  status: string;
  last_used_at: string | null;
}

export interface ActivityView {
  id?: string;
  action?: string;
  result?: string;
  created_at?: string;
}

interface Props {
  copy: Copy;
  providers: ProviderView[];
  connections: ConnectionView[];
  activity: ActivityView[];
  selectedId: string | null;
  onConnect: (provider: string) => void;
  onDisconnect: (id: string) => void;
  onSelect: (id: string) => void;
}

export function ConnectionManager({
  copy,
  providers,
  connections,
  activity,
  selectedId,
  onConnect,
  onDisconnect,
  onSelect,
}: Props) {
  return (
    <div className="cw-memory">
      <header className="cw-memory-head">
        <div>
          <h1>{copy.connections}</h1>
          <p className="cw-muted">{copy.connectionHint}</p>
        </div>
      </header>
      <ul className="cw-memory-list">
        {providers.map((provider) => {
          const live = connections.find(
            (item) => item.provider === provider.id && item.status === 'active',
          );
          return (
            <li key={provider.id} className="cw-memory-card">
              <strong>
                {provider.display_name}
                {live?.account_label ? ` — ${live.account_label}` : ''}
              </strong>
              <p className="cw-muted">{live ? copy.connected : copy.notConnected}</p>
              <ul>
                {provider.scopes.map((scope) => (
                  <li key={scope.key}>
                    {scope.display_name}
                    {live?.granted_scopes.includes(scope.key) ? ' ✓' : ''}
                  </li>
                ))}
              </ul>
              <div className="cw-row">
                {live ? (
                  <>
                    <button type="button" className="cw-btn" onClick={() => onSelect(live.id)}>
                      {copy.activity}
                    </button>
                    <button type="button" className="cw-btn cw-btn-ghost" onClick={() => onDisconnect(live.id)}>
                      {copy.disconnect}
                    </button>
                  </>
                ) : (
                  <button type="button" className="cw-btn cw-btn-primary" onClick={() => onConnect(provider.id)}>
                    {copy.connect}
                  </button>
                )}
              </div>
              {live?.last_used_at ? (
                <p className="cw-muted">
                  {copy.lastUsed}: {live.last_used_at}
                </p>
              ) : null}
              {selectedId && live?.id === selectedId && activity.length ? (
                <ul>
                  {activity.map((row, index) => (
                    <li key={row.id ?? String(index)}>
                      {row.action} {row.result}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
