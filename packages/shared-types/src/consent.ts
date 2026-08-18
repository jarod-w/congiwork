/**
 * Consent 相关类型（docs/design/00-conventions.md §3 / §4）。
 *
 * ⚠ Scope 的**内容**不在这里硬编码 —— 单一事实来源是 config/scopes.yaml，
 * 前端从 `GET /api/v1/scopes` 拉取。在前端复制一份 Scope 列表，
 * 就等于有了第二个事实来源，两边迟早不一致。
 */

export type Risk = 'read' | 'write' | 'irreversible';
export type TrustLevel = 'L1' | 'L2' | 'L3' | 'L4';
export type ConsentAction = 'granted' | 'revoked' | 'expired';
export type Surface = 'web' | 'desktop' | 'browser_ext';

/** 授权卡片需要的四段文案（P0-07 §6.1）。四段缺一不可。 */
export interface ScopeCopy {
  /** 会做什么 */
  display_name: string;
  collects: string;
  /** 会留下什么 */
  retention: string;
  /** 不开启也可以 —— 必须是真实可用的替代路径，不得是「功能不可用」 */
  degraded_behavior: string;
}

export interface ScopeSpec {
  key: string;
  trust_level: TrustLevel;
  risk: Risk;
  copy: ScopeCopy;
  requires_os_permission?: string[];
}

/** 用户可选动作固定为四种（00-conventions.md §4）。 */
export const APPROVAL_ACTIONS = [
  'approve',
  'edit_and_approve',
  'reject',
  /** 对 risk='irreversible' 不可用 —— 硬约束 4 */
  'always_allow_this_scope',
] as const;

export type ApprovalAction = (typeof APPROVAL_ACTIONS)[number];

export interface ApprovalRequest {
  approval_id: string;
  task_id: string;
  step_id: string;
  scope: string;
  risk: Risk;
  title: string;
  preview: { type: 'email' | 'table' | 'diff' | 'text'; data: Record<string, unknown> };
  editable_fields: string[];
  expires_at: string;
}
