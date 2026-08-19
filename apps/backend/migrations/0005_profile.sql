-- 0005_profile —— Personal Profile (P0-01 §4) + B7 archive-and-create
--
-- Profile is a separate table from Memory: it is injected in full every turn
-- and cached; Memory is retrieved top-k. Mixing the two would force special
-- cases into the retrieval layer.
--
-- user_id is a PARTIAL unique index (archived_at IS NULL), not UNIQUE.
-- B7: archive + create a new profile. A plain UNIQUE would make archive
-- equivalent to delete.

CREATE TABLE profile (
    id              uuid PRIMARY KEY,
    user_id         uuid NOT NULL,
    org_id          uuid NULL,
    version         int  NOT NULL DEFAULT 1,
    completed       boolean NOT NULL DEFAULT false,
    archived_at     timestamptz NULL,
    archive_reason  text NULL,
    created_at      timestamptz NOT NULL,
    updated_at      timestamptz NOT NULL
);

CREATE UNIQUE INDEX profile_one_active_per_user
    ON profile (user_id) WHERE archived_at IS NULL;

CREATE INDEX profile_user_idx ON profile (user_id, created_at DESC);

CREATE TABLE profile_field (
    id          uuid PRIMARY KEY,
    profile_id  uuid NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
    user_id     uuid NOT NULL,
    key         text NOT NULL,
    value       jsonb NOT NULL,
    source      text NOT NULL CHECK (source IN ('interview', 'manual', 'extracted')),
    confidence  real NOT NULL DEFAULT 1.0,
    status      text NOT NULL CHECK (status IN ('pending', 'active', 'rejected', 'stale')),
    evidence    jsonb NULL,
    created_at  timestamptz NOT NULL,
    updated_at  timestamptz NOT NULL
);

CREATE UNIQUE INDEX profile_field_one_active
    ON profile_field (profile_id, key) WHERE status = 'active';

CREATE INDEX profile_field_user_status_idx
    ON profile_field (user_id, status);

CREATE TABLE interview_session (
    id            uuid PRIMARY KEY,
    user_id       uuid NOT NULL,
    profile_id    uuid NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
    status        text NOT NULL CHECK (
                      status IN ('not_started', 'in_progress', 'awaiting_summary', 'skipped', 'completed')
                  ),
    round         int  NOT NULL DEFAULT 1,
    question_key  text NULL,
    answers       jsonb NOT NULL DEFAULT '{}',
    created_at    timestamptz NOT NULL,
    updated_at    timestamptz NOT NULL
);

CREATE UNIQUE INDEX interview_one_open
    ON interview_session (profile_id)
    WHERE status IN ('not_started', 'in_progress', 'awaiting_summary');
