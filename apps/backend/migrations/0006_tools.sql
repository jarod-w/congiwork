-- 0006_tools —— MCP connections + envelope-encrypted credentials (P0-05 §5)
--
-- Ciphertext is a token bundle. The DEK is unique per row and wrapped by the
-- KMS/master key. Rotating the master key re-wraps DEKs; it does not
-- re-encrypt every bundle. Plaintext tokens exist only in memory for a
-- single call (hard constraint 9).

CREATE TABLE tool_connection (
    id              uuid PRIMARY KEY,
    user_id         uuid NOT NULL,
    provider        text NOT NULL,
    account_label   text NULL,
    granted_scopes  text[] NOT NULL,
    oauth_scopes    text[] NOT NULL,
    status          text NOT NULL CHECK (status IN ('active', 'expired', 'revoked', 'error')),
    last_used_at    timestamptz NULL,
    last_error      jsonb NULL,
    created_at      timestamptz NOT NULL,
    updated_at      timestamptz NOT NULL
);

CREATE UNIQUE INDEX tool_connection_active_account
    ON tool_connection (user_id, provider, account_label)
    WHERE status <> 'revoked';

CREATE INDEX tool_connection_user_idx
    ON tool_connection (user_id, status, updated_at DESC);

CREATE TABLE tool_credential (
    connection_id uuid PRIMARY KEY REFERENCES tool_connection(id) ON DELETE CASCADE,
    ciphertext    bytea NOT NULL,
    dek_wrapped   bytea NOT NULL,
    key_version   int NOT NULL,
    expires_at    timestamptz NULL,
    updated_at    timestamptz NOT NULL
);

CREATE TABLE oauth_state (
    state         text PRIMARY KEY,
    user_id       uuid NOT NULL,
    provider      text NOT NULL,
    granted_scopes text[] NOT NULL,
    created_at    timestamptz NOT NULL
);
