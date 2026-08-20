import type { Copy } from './types';

export interface CustomProviderView {
  id: string;
  name: string;
  base_url: string;
  model: string;
  capabilities: { tool_use?: boolean };
  status: string;
}

interface Props {
  copy: Copy;
  provider: CustomProviderView | null;
  granted: boolean;
  onSave: (body: { name: string; base_url: string; model: string; api_key: string }) => void;
  onDelete: () => void;
  onEnableScope: () => void;
}

export function CustomProviderSettings({
  copy,
  provider,
  granted,
  onSave,
  onDelete,
  onEnableScope,
}: Props) {
  return (
    <section className="cw-memory-card">
      <h2>{copy.customModel}</h2>
      <p className="cw-muted">{copy.customModelHint}</p>
      {!granted ? (
        <button type="button" className="cw-btn" onClick={onEnableScope}>
          {copy.enable}
        </button>
      ) : (
        <form
          className="cw-custom-form"
          onSubmit={(event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            onSave({
              name: String(data.get('name') || ''),
              base_url: String(data.get('base_url') || ''),
              model: String(data.get('model') || ''),
              api_key: String(data.get('api_key') || ''),
            });
          }}
        >
          <input name="name" placeholder={copy.customModel} defaultValue={provider?.name ?? ''} />
          <input name="base_url" placeholder="https://" defaultValue={provider?.base_url ?? ''} />
          <input name="model" placeholder="model" defaultValue={provider?.model ?? ''} />
          <input name="api_key" type="password" placeholder="api key" />
          <div className="cw-row">
            <button type="submit" className="cw-btn cw-btn-primary">
              {copy.saveSkill}
            </button>
            {provider ? (
              <button type="button" className="cw-btn cw-btn-ghost" onClick={onDelete}>
                {copy.delete}
              </button>
            ) : null}
          </div>
          {provider && !provider.capabilities.tool_use ? (
            <p className="cw-muted">{copy.customNoTools}</p>
          ) : null}
        </form>
      )}
    </section>
  );
}
