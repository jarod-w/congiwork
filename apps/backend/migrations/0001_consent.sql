-- 0001_consent —— Consent 与审计的基础表
--
-- 约定（docs/design/00-conventions.md §2）：
--   · 主键 uuid（应用侧生成 UUIDv7，见 core/ids.py）
--   · 时间统一 timestamptz 存 UTC，字段名 *_at
--   · 枚举用 text + CHECK，不用 PG enum（避免迁移成本）
--
-- 设计见 docs/design/P0-07-consent-and-audit.md §4 / §5。

-- ── 授权记录：append-only ──
--
-- 撤销不是删除记录，而是追加一条 action='revoked'。
-- 这样任意历史时刻的授权状态都可重放 —— 审计可信度建立在这上面。
-- 因此本表**没有 UPDATE 和 DELETE 的合法用途**（账号删除时的匿名化除外，见 B1）。

CREATE TABLE consent_record (
    id                    uuid PRIMARY KEY,
    user_id               uuid NOT NULL,
    scope_key             text NOT NULL,
    action                text NOT NULL CHECK (action IN ('granted', 'revoked', 'expired')),
    always_allow          boolean NOT NULL DEFAULT false,
    surface               text NOT NULL CHECK (surface IN ('web', 'desktop', 'browser_ext')),
    -- 用户当时看到的说明文案版本。文案改版后能证明用户同意的是哪一版 ——
    -- 「明确说明后认可」这个模型的可验证性就在这个字段上。
    consent_text_version  text NOT NULL,
    device_info           jsonb NULL,
    -- 哈希存储，不存原始 IP（硬约束 8：只记「做了什么」，不记「内容是什么」）
    ip_hash               text NULL,
    created_at            timestamptz NOT NULL
);

CREATE INDEX consent_record_lookup_idx
    ON consent_record (user_id, scope_key, created_at DESC);

-- 当前状态的物化视图，供运行时高频查询。
-- 运行时优先读 Redis（consent:{user_id} hash），未命中回落到这里。
CREATE MATERIALIZED VIEW consent_current AS
SELECT DISTINCT ON (user_id, scope_key)
    user_id,
    scope_key,
    action,
    always_allow,
    created_at
FROM consent_record
ORDER BY user_id, scope_key, created_at DESC;

CREATE UNIQUE INDEX consent_current_pk_idx ON consent_current (user_id, scope_key);


-- ── 执行审计：按月分区 ──
--
-- 脱敏原则（硬约束 8）：记录「做了什么」，不记录「内容是什么」。
-- 收件人存数量与哈希，不存地址；邮件主题存哈希，不存明文。
-- 理由：审计日志本身若含敏感内容，它就成了新的泄露面。
-- 用户要看具体内容时去看任务对话记录 —— 那是他自己的数据，且可删。

CREATE TABLE execution_audit (
    id             uuid NOT NULL,
    user_id        uuid NOT NULL,
    task_id        uuid NULL,
    step_id        uuid NULL,
    scope_key      text NULL,
    surface        text NOT NULL CHECK (surface IN ('web', 'desktop', 'browser_ext')),
    action         text NOT NULL,               -- 例 'gmail.send_message'
    target_digest  jsonb NULL,                  -- 脱敏摘要 {"to_count":3,"subject_hash":"..."}
    result         text NOT NULL CHECK (
                       result IN ('allowed', 'denied', 'approved', 'rejected', 'failed')
                   ),
    approval_id    uuid NULL,
    error_code     text NULL,
    duration_ms    int NULL,
    created_at     timestamptz NOT NULL,
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

CREATE INDEX execution_audit_user_idx ON execution_audit (user_id, created_at DESC);
CREATE INDEX execution_audit_task_idx ON execution_audit (task_id) WHERE task_id IS NOT NULL;

-- 保留 12 个月，到期 drop 分区（P0-07 §7）。
-- 分区的创建与回收由运维任务负责，不在迁移里写死。
CREATE TABLE execution_audit_default PARTITION OF execution_audit DEFAULT;
