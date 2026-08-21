import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ApprovalCard,
  ConnectionManager,
  CaptureCard,
  Composer,
  ConsentCard,
  ContextPanel,
  CustomProviderSettings,
  EmptyState,
  MemoryBrowser,
  MessageStream,
  ProfilePage,
  PrivacyCenter,
  SkillEditor,
  SkillLibrary,
  TaskList,
  Timeline,
  WorkspaceShell,
  type ApprovalCardData,
  type ArtifactPreview,
  type ContextBundle,
  type CustomProviderView,
  type MemoryItem,
  type PresetView,
  type ScopeCard,
  type SkillView,
  type StepItem,
  type TaskSummary,
  type ProfileFieldView,
  type InterviewQuestionView,
  type ProviderView,
  type ConnectionView,
  type ActivityView,
  type TemplateView,
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

type View = 'workspace' | 'memory' | 'profile' | 'connections' | 'privacy' | 'skills';

export function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [token, setTokenState] = useState<string | null>(getToken());
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [mode, setMode] = useState<'signin' | 'register'>('register');
  const [error, setError] = useState<string | null>(null);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [taskSearch, setTaskSearch] = useState('');
  const [activeId, setActiveId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [bundle, setBundle] = useState<ContextBundle | null>(null);
  const [draft, setDraft] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [saveToMemory, setSaveToMemory] = useState(false);
  const [busy, setBusy] = useState(false);
  const [panelOpen, setPanelOpen] = useState(true);
  const [streamText, setStreamText] = useState('');
  const [view, setView] = useState<View>('workspace');
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [pendingMemories, setPendingMemories] = useState<MemoryItem[]>([]);
  const [memoryTab, setMemoryTab] = useState<'semantic' | 'preference' | 'episodic' | 'pending'>('semantic');
  const [memoryDraft, setMemoryDraft] = useState('');
  const [privacy, setPrivacy] = useState<{
    authorizations: { scope_key: string; action: string; display_name: string; trust_level: string | null; risk: string | null }[];
    activity: { id: string; summary: string; created_at: string }[];
    data: { memories: number; tasks: number; files: number };
    markets: string;
    cleanup: boolean;
  } | null>(null);
  const [blockedScope, setBlockedScope] = useState<ScopeCard | null>(null);
  const [profileFields, setProfileFields] = useState<ProfileFieldView[]>([]);
  const [profilePending, setProfilePending] = useState<ProfileFieldView[]>([]);
  const [interviewQuestion, setInterviewQuestion] = useState<InterviewQuestionView | null>(null);
  const [interviewLearned, setInterviewLearned] = useState<ProfileFieldView[]>([]);
  const [interviewDraft, setInterviewDraft] = useState('');
  const [interviewSelected, setInterviewSelected] = useState<string[]>([]);
  const [profileCompleted, setProfileCompleted] = useState(false);
  const [archivedCount, setArchivedCount] = useState(0);
  const [providers, setProviders] = useState<ProviderView[]>([]);
  const [connections, setConnections] = useState<ConnectionView[]>([]);
  const [connectionActivity, setConnectionActivity] = useState<ActivityView[]>([]);
  const [selectedConnection, setSelectedConnection] = useState<string | null>(null);
  const [skills, setSkills] = useState<SkillView[]>([]);
  const [presets, setPresets] = useState<PresetView[]>([]);
  const [editingSkill, setEditingSkill] = useState<SkillView | null>(null);
  const [skillMissing, setSkillMissing] = useState<string[]>([]);
  const [skillUnresolved, setSkillUnresolved] = useState<{ step_id: string; title: string; candidates: string[] }[]>([]);
  const [templates, setTemplates] = useState<TemplateView[]>([]);
  const [customProvider, setCustomProvider] = useState<CustomProviderView | null>(null);
  const [customGranted, setCustomGranted] = useState(false);
  const [paramInputs, setParamInputs] = useState<Record<string, string>>({});
  // 换技能就清掉上一份参数 —— 否则上一个技能填的值会被带进下一个技能的运行请求。
  useEffect(() => setParamInputs({}), [editingSkill?.id]);
  const [openArtifact, setOpenArtifact] = useState<string | null>(null);
  const [artifactPreviews, setArtifactPreviews] = useState<Record<string, ArtifactPreview>>({});
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
    // 首次加载与搜索走同一条路。250ms 去抖：搜索是一次请求，不该按键就发。
    const timer = window.setTimeout(() => void refreshTasks(taskSearch), taskSearch ? 250 : 0);
    return () => window.clearTimeout(timer);
  }, [token, taskSearch]);

  useEffect(() => {
    if (!token || view !== 'memory') return;
    void refreshMemories();
  }, [token, view, memoryTab]);

  useEffect(() => {
    if (!token || view !== 'privacy') return;
    void refreshPrivacy();
  }, [token, view]);

  useEffect(() => {
    if (!token || view !== 'profile') return;
    void refreshProfile();
  }, [token, view]);

  useEffect(() => {
    if (!token || view !== 'connections') return;
    void refreshConnections();
    void refreshCustomProvider();
  }, [token, view]);

  useEffect(() => {
    if (!token || view !== 'skills') return;
    void refreshSkills();
  }, [token, view]);

  useEffect(() => {
    if (!token) return;
    void api<{ templates: TemplateView[] }>('/api/v1/templates').then((body) => setTemplates(body.templates));
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
    void api<ContextBundle>(`/api/v1/tasks/${activeId}/context`).then((next) => {
      setBundle(next);
      if (next.blocked_scope) setBlockedScope(next.blocked_scope);
    });
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
          if (
            event.event === 'task.status' ||
            event.event === 'task.finished' ||
            event.event === 'artifact.created' ||
            event.event === 'approval.requested' ||
            event.event === 'memory.candidate' ||
            event.event === 'tool.result'
          ) {
            void api<TaskDetail>(`/api/v1/tasks/${activeId}`).then(setDetail);
            void api<ContextBundle>(`/api/v1/tasks/${activeId}/context`).then((next) => {
              setBundle(next);
              if (next.blocked_scope) setBlockedScope(next.blocked_scope);
            });
            void refreshTasks();
            void refreshMemories();
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

  async function refreshTasks(query: string = taskSearch) {
    // 搜索在服务端做（WS-1）：本地只有已加载的那一页，过滤它会漏掉真正的历史。
    const suffix = query.trim() ? `?q=${encodeURIComponent(query.trim())}` : '';
    const body = await api<{ tasks: TaskSummary[] }>(`/api/v1/tasks${suffix}`);
    setTasks(body.tasks);
  }

  async function loadPreview(id: string) {
    if (openArtifact === id) {
      setOpenArtifact(null);
      return;
    }
    setOpenArtifact(id);
    if (artifactPreviews[id]) return;
    const body = await api<{ preview: ArtifactPreview }>(`/api/v1/artifacts/${id}/preview`);
    setArtifactPreviews((current) => ({ ...current, [id]: body.preview }));
  }

  async function refreshMemories() {
    const pending = await api<{ memories: MemoryItem[] }>('/api/v1/memories/pending');
    setPendingMemories(pending.memories);
    if (memoryTab === 'pending') {
      setMemories(pending.memories);
      return;
    }
    const body = await api<{ memories: MemoryItem[] }>(`/api/v1/memories?type=${memoryTab}&status=active`);
    setMemories(body.memories);
  }

  async function refreshPrivacy() {
    const overview = await api<{
      authorizations: { scope_key: string; action: string; display_name: string; trust_level: string | null; risk: string | null }[];
      data: { memories: number; tasks: number; files: number };
      settings: { episodic_auto_cleanup: boolean };
      boundaries: { markets: string };
    }>('/api/v1/privacy');
    const audit = await api<{ events: { id: string; summary: string; created_at: string }[] }>('/api/v1/privacy/audit');
    setPrivacy({
      authorizations: overview.authorizations,
      activity: audit.events,
      data: overview.data,
      markets: overview.boundaries.markets,
      cleanup: overview.settings.episodic_auto_cleanup,
    });
  }

  async function refreshProfile() {
    const body = await api<{
      profile: { completed: boolean };
      fields: ProfileFieldView[];
      archived: { id: string }[];
      interview: { status: string } | null;
    }>('/api/v1/profile');
    setProfileFields(body.fields.filter((item) => item.status === 'active'));
    setProfilePending(body.fields.filter((item) => item.status === 'pending'));
    setProfileCompleted(body.profile.completed);
    setArchivedCount(body.archived.length);
    setInterviewLearned(body.fields.filter((item) => item.status === 'active'));
    if (body.interview && (body.interview.status === 'in_progress' || body.interview.status === 'awaiting_summary')) {
      const started = await api<{
        question: InterviewQuestionView | null;
        learned: ProfileFieldView[];
      }>('/api/v1/profile/interview/start', { method: 'POST' });
      setInterviewQuestion(started.question);
      setInterviewLearned(started.learned);
    }
  }

  async function refreshConnections() {
    const listed = await api<{ providers: ProviderView[] }>('/api/v1/tools/providers');
    const live = await api<{ connections: ConnectionView[] }>('/api/v1/tools/connections');
    setProviders(listed.providers);
    setConnections(live.connections);
  }

  async function refreshSkills() {
    const body = await api<{ skills: SkillView[]; presets: PresetView[] }>('/api/v1/skills/library');
    setSkills(body.skills);
    setPresets(body.presets);
  }

  async function refreshCustomProvider() {
    const body = await api<{ provider: CustomProviderView | null; scope_granted: boolean }>('/api/v1/llm/custom');
    setCustomProvider(body.provider);
    setCustomGranted(body.scope_granted);
  }

  async function openSkill(id: string) {
    const body = await api<{ skill: SkillView }>(`/api/v1/skills/${id}`);
    const check = await api<{
      missing_scopes: string[];
      unresolved_tools: { step_id: string; title: string; candidates: string[] }[];
    }>(`/api/v1/skills/${id}/precheck`, { method: 'POST' });
    setEditingSkill(body.skill);
    setSkillMissing(check.missing_scopes);
    setSkillUnresolved(check.unresolved_tools);
    setView('skills');
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
        data.append('persist', saveToMemory ? 'true' : 'false');
        const uploaded = await api<{ id: string }>('/api/v1/files', { method: 'POST', body: data });
        fileIds = [uploaded.id];
        if (saveToMemory) {
          await api(`/api/v1/files/${uploaded.id}/ingest`, { method: 'POST' });
        }
      }
      const created = await api<TaskDetail>('/api/v1/tasks', {
        method: 'POST',
        body: JSON.stringify({ message: draft, file_ids: fileIds, surface: 'web' }),
      });
      setDraft('');
      setFile(null);
      setSaveToMemory(false);
      setActiveId(created.id);
      setView('workspace');
      await refreshTasks();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed');
    } finally {
      setBusy(false);
    }
  }

  const approval: ApprovalCardData | null = bundle?.pending_approval ?? null;
  const blocked = blockedScope ?? bundle?.blocked_scope ?? null;

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
      panelOpen={panelOpen && view === 'workspace'}
      sidebar={
        <>
          <nav className="cw-nav">
            <button type="button" className={view === 'workspace' ? 'cw-btn cw-btn-primary cw-btn-block' : 'cw-btn cw-btn-block'} onClick={() => setView('workspace')}>
              {copy.workspace}
            </button>
            <button type="button" className={view === 'memory' ? 'cw-btn cw-btn-primary cw-btn-block' : 'cw-btn cw-btn-block'} onClick={() => setView('memory')}>
              {copy.memory}
            </button>
            <button type="button" className={view === 'profile' ? 'cw-btn cw-btn-primary cw-btn-block' : 'cw-btn cw-btn-block'} onClick={() => setView('profile')}>
              {copy.profile}
            </button>
            <button type="button" className={view === 'skills' ? 'cw-btn cw-btn-primary cw-btn-block' : 'cw-btn cw-btn-block'} onClick={() => setView('skills')}>
              {copy.skills}
            </button>
            <button type="button" className={view === 'connections' ? 'cw-btn cw-btn-primary cw-btn-block' : 'cw-btn cw-btn-block'} onClick={() => setView('connections')}>
              {copy.connections}
            </button>
            <button type="button" className={view === 'privacy' ? 'cw-btn cw-btn-primary cw-btn-block' : 'cw-btn cw-btn-block'} onClick={() => setView('privacy')}>
              {copy.privacy}
            </button>
          </nav>
          {view === 'workspace' ? (
            <TaskList
              copy={copy}
              tasks={tasks}
              activeId={activeId}
              search={taskSearch}
              onSearch={setTaskSearch}
              onSelect={setActiveId}
              onNew={() => {
                setActiveId(null);
                setDetail(null);
                setBundle(null);
                setStreamText('');
              }}
            />
          ) : null}
        </>
      }
      main={
        view === 'memory' ? (
          <MemoryBrowser
            copy={copy}
            items={memories}
            pending={pendingMemories}
            tab={memoryTab}
            draft={memoryDraft}
            onTab={setMemoryTab}
            onDraft={setMemoryDraft}
            onRemember={() => {
              void api('/api/v1/memories', {
                method: 'POST',
                body: JSON.stringify({ type: 'semantic', content: memoryDraft }),
              }).then(() => {
                setMemoryDraft('');
                void refreshMemories();
              });
            }}
            onConfirm={(id, accept) => {
              void api(`/api/v1/memories/${id}/confirm`, {
                method: 'POST',
                body: JSON.stringify({ action: accept ? 'accept' : 'reject' }),
              }).then(() => void refreshMemories());
            }}
            onDelete={(id) => {
              void api(`/api/v1/memories/${id}`, { method: 'DELETE' }).then(() => void refreshMemories());
            }}
            onDeleteAll={() => {
              void api('/api/v1/memories?all=true', { method: 'DELETE' }).then(() => void refreshMemories());
            }}
          />
        ) : view === 'profile' ? (
          <ProfilePage
            copy={copy}
            fields={profileFields}
            pending={profilePending}
            question={interviewQuestion}
            learned={interviewLearned}
            draft={interviewDraft}
            selected={interviewSelected}
            completed={profileCompleted}
            archivedCount={archivedCount}
            onDraft={setInterviewDraft}
            onToggleOption={(id) => {
              setInterviewSelected((current) =>
                current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
              );
            }}
            onAnswer={() => {
              void api<{
                question: InterviewQuestionView | null;
                learned: ProfileFieldView[];
                task?: { id: string };
              }>('/api/v1/profile/interview/answer', {
                method: 'POST',
                body: JSON.stringify({ text: interviewDraft, selected: interviewSelected }),
              }).then((body) => {
                setInterviewQuestion(body.question);
                setInterviewLearned(body.learned);
                setInterviewDraft('');
                setInterviewSelected([]);
                if (body.task?.id) {
                  setActiveId(body.task.id);
                  setView('workspace');
                }
                void refreshProfile();
              });
            }}
            onSkipQuestion={() => {
              void api<{ question: InterviewQuestionView | null; learned: ProfileFieldView[] }>(
                '/api/v1/profile/interview/skip',
                {
                  method: 'POST',
                  body: JSON.stringify({ scope: 'question' }),
                },
              ).then((body) => {
                setInterviewQuestion(body.question);
                setInterviewLearned(body.learned);
              });
            }}
            onSkipAll={() => {
              void api('/api/v1/profile/interview/skip', {
                method: 'POST',
                body: JSON.stringify({ scope: 'all' }),
              }).then(() => {
                setInterviewQuestion(null);
                void refreshProfile();
              });
            }}
            onStart={() => {
              void api<{ question: InterviewQuestionView | null; learned: ProfileFieldView[] }>(
                '/api/v1/profile/interview/start',
                { method: 'POST' },
              ).then((body) => {
                setInterviewQuestion(body.question);
                setInterviewLearned(body.learned);
              });
            }}
            onComplete={() => {
              void api('/api/v1/profile/interview/complete', { method: 'POST' }).then(() => void refreshProfile());
            }}
            onConfirmPending={(id, accept) => {
              void api(`/api/v1/profile/fields/${id}/confirm`, {
                method: 'POST',
                body: JSON.stringify({ action: accept ? 'accept' : 'reject' }),
              }).then(() => void refreshProfile());
            }}
            onDeleteField={(key) => {
              void api(`/api/v1/profile/fields/${key}`, { method: 'DELETE' }).then(() => void refreshProfile());
            }}
            onArchive={() => {
              void api('/api/v1/profile/archive', {
                method: 'POST',
                body: JSON.stringify({ reason: 'changed role' }),
              }).then(() => void refreshProfile());
            }}
          />
        ) : view === 'connections' ? (
          <>
          <ConnectionManager
            copy={copy}
            providers={providers}
            connections={connections}
            activity={connectionActivity}
            selectedId={selectedConnection}
            onConnect={(provider) => {
              void api<{ status: string; authorization_url?: string }>(
                '/api/v1/tools/connections',
                { method: 'POST', body: JSON.stringify({ provider }) },
              ).then((body) => {
                if (body.authorization_url) {
                  window.location.assign(body.authorization_url);
                  return;
                }
                void refreshConnections();
              });
            }}
            onDisconnect={(id) => {
              void api(`/api/v1/tools/connections/${id}`, { method: 'DELETE' }).then(() => void refreshConnections());
            }}
            onSelect={(id) => {
              setSelectedConnection(id);
              void api<{ events: ActivityView[] }>(`/api/v1/tools/connections/${id}/activity`).then((body) => {
                setConnectionActivity(body.events);
              });
            }}
          />
          <CustomProviderSettings
            copy={copy}
            provider={customProvider}
            granted={customGranted}
            onEnableScope={() => {
              void api<{ scopes: ScopeCard[] }>('/api/v1/scopes').then((body) => {
                const scope = body.scopes.find((item) => item.key === 'llm:custom:route');
                if (!scope) return;
                void api('/api/v1/consent', {
                  method: 'POST',
                  body: JSON.stringify({
                    scope_key: scope.key,
                    consent_text_version: scope.consent_text_version,
                    always_allow: true,
                  }),
                }).then(() => void refreshCustomProvider());
              });
            }}
            onSave={(form) => {
              void api('/api/v1/llm/custom', { method: 'PUT', body: JSON.stringify(form) }).then(
                () => void refreshCustomProvider(),
              );
            }}
            onDelete={() => {
              void api('/api/v1/llm/custom', { method: 'DELETE' }).then(() => void refreshCustomProvider());
            }}
          />
          </>
        ) : view === 'skills' ? (
          editingSkill ? (
            <SkillEditor
              copy={copy}
              skill={editingSkill}
              missingScopes={skillMissing}
              unresolved={skillUnresolved}
              onChange={setEditingSkill}
              onSave={() => {
                void api(`/api/v1/skills/${editingSkill.id}`, {
                  method: 'PATCH',
                  body: JSON.stringify({
                    name: editingSkill.name,
                    description: editingSkill.description,
                    workflow: editingSkill.workflow,
                    trigger: editingSkill.trigger,
                    input_schema: editingSkill.input_schema,
                  }),
                }).then(() => void openSkill(editingSkill.id));
              }}
              onActivate={() => {
                void api(`/api/v1/skills/${editingSkill.id}`, {
                  method: 'PATCH',
                  body: JSON.stringify({ status: 'active' }),
                }).then(() => void openSkill(editingSkill.id));
              }}
              onRun={(dryRun) => {
                void api<{ id: string }>(`/api/v1/skills/${editingSkill.id}/run`, {
                  method: 'POST',
                  body: JSON.stringify({ inputs: paramInputs, dry_run: dryRun }),
                }).then((task) => {
                  void api('/api/v1/events', {
                    method: 'POST',
                    body: JSON.stringify({
                      name: dryRun ? 'skill_created' : 'skill_reused',
                      payload: { skill_id: editingSkill.id },
                    }),
                  });
                  setActiveId(task.id);
                  setView('workspace');
                });
              }}
            />
          ) : (
            <SkillLibrary
              copy={copy}
              skills={skills}
              presets={presets}
              onOpen={(id) => void openSkill(id)}
              onCopyPreset={(id) => {
                void api<{ skill: SkillView }>('/api/v1/skills/draft', {
                  method: 'POST',
                  body: JSON.stringify({ preset_id: id }),
                }).then((body) => void openSkill(body.skill.id));
              }}
              onNew={() => {
                const description = window.prompt(copy.skillHint);
                if (!description) return;
                void api<{ draft: Omit<SkillView, 'id' | 'run_count' | 'success_count' | 'success_rate' | 'version'> }>(
                  '/api/v1/skills/draft',
                  { method: 'POST', body: JSON.stringify({ description }) },
                ).then((body) => {
                  void api<{ skill: SkillView }>('/api/v1/skills', {
                    method: 'POST',
                    body: JSON.stringify(body.draft),
                  }).then((created) => void openSkill(created.skill.id));
                });
              }}
            />
          )
        ) : view === 'privacy' && privacy ? (
          <PrivacyCenter
            copy={copy}
            grants={privacy.authorizations}
            activity={privacy.activity}
            data={privacy.data}
            markets={privacy.markets}
            cleanup={privacy.cleanup}
            onCleanup={(value) => {
              void api('/api/v1/privacy/settings', {
                method: 'PATCH',
                body: JSON.stringify({ episodic_auto_cleanup: value }),
              }).then(() => void refreshPrivacy());
            }}
            onRevoke={(scope) => {
              void api(`/api/v1/consent/${scope}`, { method: 'DELETE' }).then(() => void refreshPrivacy());
            }}
            onExport={() => {
              void api('/api/v1/privacy/export').then((body) => {
                const blob = new Blob([JSON.stringify(body, null, 2)], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const anchor = document.createElement('a');
                anchor.href = url;
                anchor.download = 'cogniwork-export.json';
                anchor.click();
                URL.revokeObjectURL(url);
              });
            }}
            onDeleteAccount={() => {
              void api('/api/v1/privacy/account', { method: 'DELETE' }).then(() => {
                clearToken();
                setTokenState(null);
              });
            }}
          />
        ) : (
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
                {approval ? (
                  <ApprovalCard
                    copy={copy}
                    approval={approval}
                    onResolve={(action, edited) => {
                      void api(`/api/v1/approvals/${approval.approval_id}/resolve`, {
                        method: 'POST',
                        body: JSON.stringify({ action, edited }),
                      }).then(() => {
                        void api<TaskDetail>(`/api/v1/tasks/${activeId}`).then(setDetail);
                        if (activeId) void api<ContextBundle>(`/api/v1/tasks/${activeId}/context`).then(setBundle);
                      });
                    }}
                  />
                ) : null}
                {blocked ? (
                  <ConsentCard
                    copy={copy}
                    scope={blocked}
                    onEnable={() => {
                      void api('/api/v1/consent', {
                        method: 'POST',
                        body: JSON.stringify({
                          scope_key: blocked.key,
                          consent_text_version: blocked.consent_text_version,
                          always_allow: true,
                        }),
                      }).then(() => setBlockedScope(null));
                    }}
                    onSkip={() => setBlockedScope(null)}
                  />
                ) : null}
                <MessageStream text={streamText || detail.result?.summary || ''} />
                <CaptureCard
                  copy={copy}
                  items={pendingMemories.filter((item) => item.source_ref && (item.source_ref as { task_id?: string }).task_id === detail.id)}
                  profileItems={(bundle?.pending_profile ?? []).map((item) => ({
                    id: item.id,
                    key: item.key,
                    value: item.value,
                  }))}
                  onKeep={() => {
                    pendingMemories
                      .filter((item) => (item.source_ref as { task_id?: string } | null)?.task_id === detail.id)
                      .forEach((item) => {
                        void api(`/api/v1/memories/${item.id}/confirm`, {
                          method: 'POST',
                          body: JSON.stringify({ action: 'accept' }),
                        });
                      });
                    (bundle?.pending_profile ?? []).forEach((item) => {
                      void api(`/api/v1/profile/fields/${item.id}/confirm`, {
                        method: 'POST',
                        body: JSON.stringify({ action: 'accept' }),
                      });
                    });
                    void refreshMemories();
                    void refreshProfile();
                  }}
                  onSkip={() => undefined}
                />
                <button
                  type="button"
                  className="cw-btn"
                  onClick={() => {
                    void api<{ draft: Record<string, unknown> }>('/api/v1/skills/draft', {
                      method: 'POST',
                      body: JSON.stringify({ task_id: detail.id }),
                    }).then((body) => {
                      void api<{ skill: SkillView }>('/api/v1/skills', {
                        method: 'POST',
                        body: JSON.stringify(body.draft),
                      }).then((created) => void openSkill(created.skill.id));
                    });
                  }}
                >
                  {copy.saveAsSkill}
                </button>
              </>
            ) : (
              <EmptyState
                copy={copy}
                templates={templates}
                onUse={(template) => {
                  setDraft(template.prompt);
                  void api('/api/v1/events', {
                    method: 'POST',
                    body: JSON.stringify({ name: 'template_used', payload: { template_id: template.id } }),
                  });
                }}
              />
            )}
            <Composer
              copy={copy}
              value={draft}
              busy={busy}
              fileName={file?.name ?? null}
              saveToMemory={saveToMemory}
              onChange={setDraft}
              onFile={setFile}
              onSaveToMemory={setSaveToMemory}
              onSubmit={() => void submitTask()}
            />
          </div>
        )
      }
      panel={
        <ContextPanel
          copy={copy}
          bundle={bundle}
          open={panelOpen}
          onToggle={() => setPanelOpen((value) => !value)}
          onDownload={(id, filename) => void downloadArtifact(id, filename)}
          onPreview={(id) => void loadPreview(id)}
          previews={artifactPreviews}
          openArtifact={openArtifact}
        />
      }
    />
  );
}
