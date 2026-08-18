/**
 * Task 执行期间的 SSE 事件（docs/design/00-conventions.md §7）。
 *
 * 长任务与流式输出统一走 SSE，不用 WebSocket（Phase 1 无双向低延时需求）。
 */

export const TASK_EVENTS = [
  'task.created',
  'task.status',
  'plan.updated',
  'step.started',
  'step.finished',
  'tool.call',
  'tool.result',
  'message.delta',
  'approval.requested',
  'approval.resolved',
  'artifact.created',
  'memory.candidate',
  'task.finished',
] as const;

export type TaskEventName = (typeof TASK_EVENTS)[number];

/** 所有事件共有的字段。`seq` 单调递增，用于断线重连补发。 */
export interface TaskEventBase {
  event: TaskEventName;
  task_id: string;
  ts: string;
  seq: number;
}

export type TaskTerminalStatus = 'succeeded' | 'failed' | 'cancelled' | 'timeout';
