-- 0004_memory —— Memory OS + 审批请求 + 用户设置
--
-- 设计见 docs/design/P0-02-memory-os.md §4 / §6、P0-03 §6、B6。
-- 主键 UUIDv7、时间 timestamptz、枚举 text+CHECK（00-conventions.md §2）。
--
-- embedding 用 real[] 而不是 pgvector：CI 与官方 postgres:16 镜像没有
-- vector 扩展。仍是「一套 PostgreSQL 存储、不引入独立向量库」（计划 §7.7）。
-- Phase 1 单用户数百到数千条，余弦计算在应用层即可。生产若装了 pgvector，
-- 后续迁移可以把列改成 vector(1024) 并建 HNSW，接口不用动。

CREATE TABLE memory_item (
    id              uuid PRIMARY KEY,
    user_id         uuid NOT NULL,
    type            text NOT NULL CHECK (type IN ('semantic', 'episodic', 'preference')),
    subtype         text NULL,
    content         text NOT NULL,
    summary         text NULL,
    embedding       real[] NULL,
    embed_model     text NULL,
    tsv             tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,

    importance      smallint NOT NULL DEFAULT 3 CHECK (importance BETWEEN 1 AND 5),
    confidence      real NOT NULL DEFAULT 1.0,

    source_type     text NOT NULL CHECK (
                        source_type IN (
                            'user_explicit', 'task_extracted', 'file_ingest',
                            'approval_edit', 'system'
                        )
                    ),
    source_ref      jsonb NULL,
    scope_key       text NULL,

    status          text NOT NULL CHECK (
                        status IN ('pending', 'active', 'superseded', 'rejected')
                    ),
    superseded_by   uuid NULL REFERENCES memory_item(id),
    conflict_with   uuid NULL REFERENCES memory_item(id),

    valid_from      timestamptz NOT NULL,
    valid_to        timestamptz NULL,
    last_used_at    timestamptz NULL,
    use_count       int NOT NULL DEFAULT 0,

    created_at      timestamptz NOT NULL,
    updated_at      timestamptz NOT NULL
);

CREATE INDEX memory_item_user_type_idx
    ON memory_item (user_id, type, status, updated_at DESC);
CREATE INDEX memory_item_scope_idx
    ON memory_item (user_id, scope_key) WHERE scope_key IS NOT NULL;
CREATE INDEX memory_item_tsv_idx
    ON memory_item USING gin (tsv) WHERE status = 'active';

CREATE TABLE episodic_record (
    id            uuid PRIMARY KEY,
    memory_id     uuid NOT NULL REFERENCES memory_item(id) ON DELETE CASCADE,
    user_id       uuid NOT NULL,
    task_id       uuid NOT NULL,
    title         text NOT NULL,
    intent        text NULL,
    tools_used    text[] NOT NULL DEFAULT '{}',
    skill_id      uuid NULL,
    outcome       text NOT NULL CHECK (
                      outcome IN ('succeeded', 'failed', 'cancelled', 'partial')
                  ),
    decisions     jsonb NOT NULL DEFAULT '[]',
    user_edits    jsonb NOT NULL DEFAULT '[]',
    duration_ms   int NULL,
    started_at    timestamptz NOT NULL,
    ended_at      timestamptz NULL
);

CREATE INDEX episodic_record_user_idx ON episodic_record (user_id, started_at DESC);
CREATE INDEX episodic_record_task_idx ON episodic_record (task_id);
CREATE INDEX episodic_record_intent_idx
    ON episodic_record (user_id, intent, started_at DESC) WHERE intent IS NOT NULL;

-- B6：开关必须出现在设置界面上，默认关闭。Phase 1 永久保留任务历史。
CREATE TABLE user_settings (
    user_id                      uuid PRIMARY KEY,
    episodic_auto_cleanup        boolean NOT NULL DEFAULT false,
    episodic_retention_months    int NOT NULL DEFAULT 12
                                     CHECK (episodic_retention_months BETWEEN 1 AND 120),
    created_at                   timestamptz NOT NULL,
    updated_at                   timestamptz NOT NULL
);

CREATE TABLE approval_request (
    id                  uuid PRIMARY KEY,
    user_id             uuid NOT NULL,
    task_id             uuid NOT NULL,
    step_id             uuid NULL,
    tool_name           text NOT NULL,
    scope_key           text NULL,
    risk                text NOT NULL CHECK (risk IN ('read', 'write', 'irreversible')),
    title               text NOT NULL,
    arguments           jsonb NOT NULL,
    preview             jsonb NOT NULL,
    preview_renderer    text NOT NULL CHECK (
                            preview_renderer IN ('email', 'table', 'diff', 'text')
                        ),
    editable_fields     text[] NOT NULL DEFAULT '{}',
    status              text NOT NULL CHECK (
                            status IN (
                                'pending', 'approved', 'rejected',
                                'edited', 'skipped', 'timed_out'
                            )
                        ),
    edited_arguments    jsonb NULL,
    expires_at          timestamptz NOT NULL,
    resolved_at         timestamptz NULL,
    created_at          timestamptz NOT NULL
);

CREATE INDEX approval_request_task_idx ON approval_request (task_id, created_at DESC);
CREATE INDEX approval_request_user_pending_idx
    ON approval_request (user_id, status) WHERE status = 'pending';
