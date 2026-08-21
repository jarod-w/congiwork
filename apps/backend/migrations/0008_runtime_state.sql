-- 0008_runtime_state —— 任务运行态
--
-- 设计见 docs/design/P0-03-agent-runtime.md RT-5 / §12 验收 1。

-- 消息历史、用到的记忆、被拦下的 Scope、挂起的工具调用、Skill 游标。
-- 原先是 TaskEngine 上的进程内 dict，重启即丢；而审批可以等 24 小时
-- （approvals.APPROVAL_TTL）。用户回来点「批准」，Runtime 必须还知道要执行什么。
--
-- 与 task 同寿命：任务进终态时 Runtime 扔掉执行用的那部分（见 runtime/state.py
-- 的 finish），账号删除随 task 级联物理删除。
--
-- 这里存的是用户自己的任务正文，不是审计记录 —— 硬约束 8 约束的是
-- execution_audit，那张表仍然只记「做了什么」。
CREATE TABLE task_runtime_state (
    task_id     uuid PRIMARY KEY REFERENCES task(id) ON DELETE CASCADE,
    payload     jsonb NOT NULL,
    updated_at  timestamptz NOT NULL
);

-- execution_audit 的按月分区**不在这里建**。
--
-- 0001 那句「分区的创建与回收由运维任务负责，不在迁移里写死」现在有执行者了：
-- src/cogniwork/maintenance.py（`python -m cogniwork.maintenance audit-retention`，
-- 建分区那一半 API 启动时也会跑一次）。分区逻辑只有一份实现，在 Python 里 ——
-- 它有单测，而迁移里的 plpgsql 没有。见 docs/deploy.md §8.1。
