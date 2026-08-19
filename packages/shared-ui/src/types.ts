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
  memories: unknown[];
  skills: unknown[];
  tools: string[];
  scopes: string[];
  files: { id: string; filename: string; size_bytes: number }[];
  artifacts: ArtifactItem[];
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
}
