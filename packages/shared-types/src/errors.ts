/**
 * 统一错误模型（docs/design/00-conventions.md §6）。
 *
 * 后端的对应定义在 apps/backend/src/cogniwork/core/errors.py。
 * 两边必须一致 —— 词表变更时同时改，别只改一边。
 */

/** 受控错误码词表。不允许临时新增字符串。 */
export const ERROR_CODES = [
  'invalid_request',
  'unauthorized',
  'permission_denied',
  'not_found',
  'conflict',
  'rate_limited',
  'upstream_error',
  'internal_error',
] as const;

export type ErrorCode = (typeof ERROR_CODES)[number];

export interface ApiError {
  error: {
    code: ErrorCode;
    message: string;
    details: Record<string, unknown>;
    trace_id: string;
  };
}
