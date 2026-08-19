-- 0007_skill —— Skill definitions + version snapshots (P0-06 §4)
--
-- success_rate is derived from success_count / run_count, never stored.
-- required_scopes is derived from workflow at write time, not user-authored.

CREATE TABLE skill (
    id               uuid PRIMARY KEY,
    user_id          uuid NOT NULL,
    name             text NOT NULL,
    description      text NOT NULL,
    trigger          jsonb NOT NULL,
    input_schema     jsonb NOT NULL,
    workflow         jsonb NOT NULL,
    tools            text[] NOT NULL DEFAULT '{}',
    required_scopes  text[] NOT NULL DEFAULT '{}',
    source           text NOT NULL CHECK (source IN ('manual', 'from_task', 'semi_auto', 'preset_copy')),
    source_ref       jsonb NULL,
    version          int NOT NULL DEFAULT 1,
    status           text NOT NULL CHECK (status IN ('draft', 'active', 'archived')),
    run_count        int NOT NULL DEFAULT 0,
    success_count    int NOT NULL DEFAULT 0,
    last_run_at      timestamptz NULL,
    created_at       timestamptz NOT NULL,
    updated_at       timestamptz NOT NULL
);

CREATE INDEX skill_user_idx ON skill (user_id, status, updated_at DESC);

CREATE TABLE skill_version (
    skill_id     uuid NOT NULL REFERENCES skill(id) ON DELETE CASCADE,
    version      int NOT NULL,
    snapshot     jsonb NOT NULL,
    changed_by   text NOT NULL CHECK (changed_by IN ('user', 'system')),
    change_note  text NULL,
    created_at   timestamptz NOT NULL,
    PRIMARY KEY (skill_id, version)
);

-- Custom LLM provider (P0-03 §7.1). api_key is envelope-encrypted like tool credentials.
CREATE TABLE custom_llm_provider (
    id              uuid PRIMARY KEY,
    user_id         uuid NOT NULL,
    name            text NOT NULL,
    base_url        text NOT NULL,
    model           text NOT NULL,
    ciphertext      bytea NOT NULL,
    dek_wrapped     bytea NOT NULL,
    key_version     int NOT NULL,
    capabilities    jsonb NOT NULL DEFAULT '{}',
    unit_cost_usd   numeric(12,6) NULL,
    status          text NOT NULL CHECK (status IN ('active', 'disabled', 'probe_failed')),
    last_probed_at  timestamptz NULL,
    created_at      timestamptz NOT NULL,
    updated_at      timestamptz NOT NULL
);

CREATE UNIQUE INDEX custom_llm_provider_user_idx
    ON custom_llm_provider (user_id)
    WHERE status <> 'disabled';

-- Daily token/cost rollup for governance (P0-03 §8).
CREATE TABLE daily_llm_usage (
    user_id     uuid NOT NULL,
    day         date NOT NULL,
    cost_usd    numeric(12,6) NOT NULL DEFAULT 0,
    token_in    int NOT NULL DEFAULT 0,
    token_out   int NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);

-- Product analytics (P0-04 §9). Not user work content; no telemetry Scope.
CREATE TABLE product_event (
    id          uuid PRIMARY KEY,
    user_id     uuid NOT NULL,
    name        text NOT NULL,
    payload     jsonb NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL
);

CREATE INDEX product_event_user_idx ON product_event (user_id, name, created_at DESC);
