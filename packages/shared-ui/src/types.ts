export interface TaskSummary {
  id: string;
  title: string | null;
  status: string;
  created_at: string;
}

export interface StepItem {
  id: string;
  seq: number;
  type: string;
  title: string;
  status: string;
  duration_ms: number | null;
}

export interface ArtifactItem {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
}

export interface ContextBundle {
  memories: MemoryRef[];
  skills: unknown[];
  tools: string[];
  scopes: string[];
  files: { id: string; filename: string; size_bytes: number }[];
  artifacts: ArtifactItem[];
  pending_approval?: ApprovalCardData | null;
  blocked_scope?: ScopeCard | null;
}

export interface MemoryRef {
  id: string;
  type: string;
  summary: string | null;
  content: string;
  source_ref?: Record<string, unknown> | null;
  score?: number;
}

export interface MemoryItem {
  id: string;
  type: string;
  subtype: string | null;
  content: string;
  summary: string | null;
  importance: number;
  source_type: string;
  source_ref: Record<string, unknown> | null;
  status: string;
  use_count: number;
  created_at: string;
  conflict_with: string | null;
}

export interface ScopeCard {
  key: string;
  trust_level: string;
  risk: string;
  consent_text_version: string;
  copy: {
    display_name: string;
    collects: string;
    retention: string;
    degraded_behavior: string;
  };
}

export interface ApprovalPreview {
  type: 'email' | 'table' | 'diff' | 'text' | string;
  data: Record<string, unknown>;
}

export interface ApprovalCardData {
  approval_id: string;
  task_id: string;
  scope: string | null;
  risk: string;
  title: string;
  preview: ApprovalPreview;
  editable_fields: string[];
  expires_at: string;
}

export interface Copy {
  appName: string;
  tagline: string;
  tasks: string;
  newTask: string;
  inProgress: string;
  today: string;
  earlier: string;
  emptyTasks: string;
  composerPlaceholder: string;
  send: string;
  attach: string;
  grounds: string;
  groundsHint: string;
  collapse: string;
  expand: string;
  artifacts: string;
  files: string;
  toolsUsed: string;
  memories: string;
  skills: string;
  noneYet: string;
  download: string;
  signIn: string;
  createAccount: string;
  email: string;
  password: string;
  working: string;
  succeeded: string;
  failed: string;
  cancelled: string;
  skipInterview: string;
  dropHint: string;
  signOut: string;
  memory: string;
  privacy: string;
  workspace: string;
  facts: string;
  preferences: string;
  history: string;
  pending: string;
  remember: string;
  rememberHint: string;
  confirm: string;
  reject: string;
  delete: string;
  deleteAll: string;
  emptyMemory: string;
  whyThis: string;
  usedNTimes: string;
  saveToMemory: string;
  captureTitle: string;
  captureKeep: string;
  captureSkip: string;
  approve: string;
  editAndApprove: string;
  skipStep: string;
  cancelTask: string;
  enable: string;
  notNow: string;
  whatThisDoes: string;
  whatWeWillNotDo: string;
  willNotBody: string;
  whatWeKeep: string;
  ifYouSkip: string;
  alwaysAllowThis: string;
  authorizations: string;
  activity: string;
  myData: string;
  exportAll: string;
  deleteAccount: string;
  cleanupLabel: string;
  cleanupHint: string;
  markets: string;
  needsConfirmation: string;
}
