-- 0003_task —— 会话、任务、步骤、上传文件、产物
--
-- 设计见 docs/design/P0-03-agent-runtime.md §3 / P0-04 §6。
-- 主键 UUIDv7、时间 timestamptz、枚举 text+CHECK（00-conventions.md §2）。

CREATE TABLE conversation (
    id          uuid PRIMARY KEY,
    user_id     uuid NOT NULL,
    title       text NULL,
    created_at  timestamptz NOT NULL,
    updated_at  timestamptz NOT NULL
);

CREATE INDEX conversation_user_idx ON conversation (user_id, updated_at DESC);

CREATE TABLE task (
    id               uuid PRIMARY KEY,
    user_id          uuid NOT NULL,
    conversation_id  uuid NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    title            text NULL,
    intent           text NULL,
    status           text NOT NULL CHECK (
        status IN (
            'created', 'planning', 'running', 'waiting_approval',
            'succeeded', 'failed', 'cancelled', 'timed_out'
        )
    ),
    surface          text NOT NULL CHECK (surface IN ('web', 'desktop', 'browser_ext', 'api')),
    skill_id         uuid NULL,
    input            jsonb NOT NULL,
    result           jsonb NULL,
    error            jsonb NULL,
    thread_id        text NOT NULL,
    cost_usd         numeric(12,6) NOT NULL DEFAULT 0,
    token_in         int NOT NULL DEFAULT 0,
    token_out        int NOT NULL DEFAULT 0,
    started_at       timestamptz NULL,
    ended_at         timestamptz NULL,
    created_at       timestamptz NOT NULL,
    updated_at       timestamptz NOT NULL
);

CREATE INDEX task_user_idx ON task (user_id, created_at DESC);
CREATE INDEX task_conversation_idx ON task (conversation_id, created_at DESC);

CREATE TABLE task_step (
    id             uuid PRIMARY KEY,
    task_id        uuid NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    seq            int NOT NULL,
    type           text NOT NULL CHECK (type IN ('llm', 'tool', 'approval', 'skill', 'subtask')),
    title          text NOT NULL,
    status         text NOT NULL CHECK (
        status IN ('pending', 'running', 'succeeded', 'failed', 'skipped')
    ),
    scope_key      text NULL,
    input_digest   jsonb NULL,
    output_digest  jsonb NULL,
    error          jsonb NULL,
    duration_ms    int NULL,
    created_at     timestamptz NOT NULL
);

CREATE UNIQUE INDEX task_step_seq_idx ON task_step (task_id, seq);

-- 用户每次显式选择上传，属 L1，不加 Scope（00-conventions.md §3 注）。
CREATE TABLE uploaded_file (
    id            uuid PRIMARY KEY,
    user_id       uuid NOT NULL,
    filename      text NOT NULL,
    content_type  text NOT NULL,
    size_bytes    int NOT NULL,
    persist       boolean NOT NULL DEFAULT false,
    content       bytea NOT NULL,
    created_at    timestamptz NOT NULL
);

CREATE INDEX uploaded_file_user_idx ON uploaded_file (user_id, created_at DESC);

CREATE TABLE artifact (
    id            uuid PRIMARY KEY,
    user_id       uuid NOT NULL,
    task_id       uuid NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    filename      text NOT NULL,
    content_type  text NOT NULL,
    size_bytes    int NOT NULL,
    content       bytea NOT NULL,
    created_at    timestamptz NOT NULL
);

CREATE INDEX artifact_task_idx ON artifact (task_id, created_at);
