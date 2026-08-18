import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Composer,
  ContextPanel,
  MessageStream,
  TaskList,
  Timeline,
  WorkspaceShell,
  type ContextBundle,
  type StepItem,
  type TaskSummary,
} from '@cogniwork/shared-ui';
import { api, clearToken, downloadArtifact, getToken, setToken } from './api';
import { catalogFor } from './i18n';
import { connectTaskEvents } from './sse';

interface Config {
  default_locale: string;
  fallback_locale: string;
  supported_locales: string[];
}

interface TaskDetail {
  id: string;
  title: string | null;
  status: string;
  created_at: string;
  input: { message: string; file_ids: string[] };
  result: { summary?: string } | null;
  steps: StepItem[];
  artifacts: ContextBundle['artifacts'];
}

export function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [token, setTokenState] = useState<string | null>(getToken());
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [mode, setMode] = useState<'signin' | 'register'>('register');
  const [error, setError] = useState<string | null>(null);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [bundle, setBundle] = useState<ContextBundle | null>(null);
  const [draft, setDraft] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [panelOpen, setPanelOpen] = useState(true);
  const [streamText, setStreamText] = useState('');
  const deltaRef = useRef('');
  const frameRef = useRef<number | null>(null);

  const copy = useMemo(
    () => catalogFor(config?.default_locale ?? '', config?.fallback_locale ?? ''),
    [config],
  );

  useEffect(() => {
    void api<Config>('/api/v1/config').then(setConfig).catch(() => {
      setConfig({ default_locale: '', fallback_locale: '', supported_locales: [] });
    });
  }, []);

  useEffect(() => {
    if (!token) return;
    void refreshTasks();
  }, [token]);

  useEffect(() => {
    if (!token || !activeId) return;
    const controller = new AbortController();
    deltaRef.current = '';
    setStreamText('');
    void api<TaskDetail>(`/api/v1/tasks/${activeId}`).then((task) => {
      setDetail(task);
      if (task.result?.summary) setStreamText(task.result.summary);
    });
    void api<ContextBundle>(`/api/v1/tasks/${activeId}/context`).then(setBundle);
    const session = connectTaskEvents(
      activeId,
      token,
      0,
      {
        onEvent(event) {
          if (event.event === 'message.delta' && event.text) {
            deltaRef.current += event.text;
            if (frameRef.current == null) {
              frameRef.current = requestAnimationFrame(() => {
                setStreamText(deltaRef.current);
                frameRef.current = null;
              });
            }
          }
          if (event.event === 'task.status' || event.event === 'task.finished' || event.event === 'artifact.created') {
            void api<TaskDetail>(`/api/v1/tasks/${activeId}`).then(setDetail);
            void api<ContextBundle>(`/api/v1/tasks/${activeId}/context`).then(setBundle);
            void refreshTasks();
          }
        },
      },
      controller.signal,
    );
    return () => {
      session.stop();
      controller.abort();
    };
  }, [token, activeId]);

  async function refreshTasks() {
    const body = await api<{ tasks: TaskSummary[] }>('/api/v1/tasks');
    setTasks(body.tasks);
  }

  async function authenticate(path: '/api/v1/auth/register' | '/api/v1/auth/login') {
    setError(null);
    try {
      const body = await api<{ access_token: string }>(path, {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      });
      setToken(body.access_token);
      setTokenState(body.access_token);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed');
    }
  }

  async function submitTask() {
    if (!draft.trim()) return;
    setBusy(true);
    setError(null);
    try {
      let fileIds: string[] = [];
      if (file) {
        const data = new FormData();
        data.append('file', file);
        data.append('persist', 'false');
        const uploaded = await api<{ id: string }>('/api/v1/files', { method: 'POST', body: data });
        fileIds = [uploaded.id];
      }
      const created = await api<TaskDetail>('/api/v1/tasks', {
        method: 'POST',
        body: JSON.stringify({ message: draft, file_ids: fileIds, surface: 'web' }),
      });
      setDraft('');
      setFile(null);
      setActiveId(created.id);
      await refreshTasks();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed');
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <div className="cw-auth">
        <div className="cw-auth-card">
          <h1 className="cw-wordmark">{copy.appName}</h1>
          <p className="cw-tagline">{copy.tagline}</p>
          <p className="cw-muted">{copy.skipInterview}</p>
          <label>
            {copy.email}
            <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" autoComplete="username" />
          </label>
          <label>
            {copy.password}
            <input
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              type="password"
              autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
            />
          </label>
          {error ? <p className="cw-error">{error}</p> : null}
          <button
            type="button"
            className="cw-btn cw-btn-primary cw-btn-block"
            onClick={() => void authenticate(mode === 'register' ? '/api/v1/auth/register' : '/api/v1/auth/login')}
          >
            {mode === 'register' ? copy.createAccount : copy.signIn}
          </button>
          <button
            type="button"
            className="cw-btn cw-btn-ghost cw-btn-block"
            onClick={() => setMode(mode === 'register' ? 'signin' : 'register')}
          >
            {mode === 'register' ? copy.signIn : copy.createAccount}
          </button>
        </div>
      </div>
    );
  }

  return (
    <WorkspaceShell
      panelOpen={panelOpen}
      sidebar={
        <TaskList
          copy={copy}
          tasks={tasks}
          activeId={activeId}
          onSelect={setActiveId}
          onNew={() => {
            setActiveId(null);
            setDetail(null);
            setBundle(null);
            setStreamText('');
          }}
        />
      }
      main={
        <div className="cw-thread">
          <header className="cw-thread-head">
            <div>
              <h1>{detail?.title || copy.newTask}</h1>
              <p className="cw-muted">{copy.dropHint}</p>
            </div>
            <button
              type="button"
              className="cw-btn cw-btn-ghost"
              onClick={() => {
                clearToken();
                setTokenState(null);
              }}
            >
                {copy.signOut}
            </button>
          </header>
          {error ? <p className="cw-error">{error}</p> : null}
          {detail ? (
            <>
              <article className="cw-message is-user">
                <pre>{detail.input.message}</pre>
              </article>
              <Timeline copy={copy} steps={detail.steps} />
              <MessageStream text={streamText || detail.result?.summary || ''} />
            </>
          ) : (
            <p className="cw-muted">{copy.emptyTasks}</p>
          )}
          <Composer
            copy={copy}
            value={draft}
            busy={busy}
            fileName={file?.name ?? null}
            onChange={setDraft}
            onFile={setFile}
            onSubmit={() => void submitTask()}
          />
        </div>
      }
      panel={
        <ContextPanel
          copy={copy}
          bundle={bundle}
          open={panelOpen}
          onToggle={() => setPanelOpen((value) => !value)}
          onDownload={(id, filename) => void downloadArtifact(id, filename)}
        />
      }
    />
  );
}
