#!/usr/bin/env bash
# CogniWork Cloud Agent — repository bootstrap. Idempotent: safe to re-run.
#
# Prepares durable state that persists into an environment-build snapshot:
#   - uv (Python package manager) + PostgreSQL 16 + Redis system packages
#   - backend virtualenv and Python deps
#   - web workspace deps (pnpm)
#   - a user-owned PostgreSQL cluster with the cogniwork role/db and migrations
#
# Per-boot service startup lives in start.sh; dev servers live in terminals.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.local/bin:/usr/lib/postgresql/16/bin:$PATH"
PGDATA="$HOME/.local/share/cogniwork/pgdata"
PGPORT=5432

echo "==> uv"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "==> system packages (PostgreSQL 16, Redis)"
if ! command -v initdb >/dev/null 2>&1 || ! command -v redis-server >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    postgresql postgresql-contrib redis-server
fi
export PATH="/usr/lib/postgresql/16/bin:$PATH"

echo "==> backend deps"
(cd "$REPO_ROOT/apps/backend" && \
  { [ -d .venv ] || uv venv --python 3.12; } && \
  uv pip install -e ".[dev]")

echo "==> web deps"
(cd "$REPO_ROOT" && pnpm install --frozen-lockfile)

echo "==> PostgreSQL cluster"
mkdir -p "$(dirname "$PGDATA")"
if [ ! -f "$PGDATA/PG_VERSION" ]; then
  initdb -D "$PGDATA" -U postgres --auth=trust
fi
if ! pg_isready -h 127.0.0.1 -p "$PGPORT" >/dev/null 2>&1; then
  pg_ctl -D "$PGDATA" -o "-p $PGPORT -k /tmp" -l "$HOME/.local/share/cogniwork/pg.log" start
  for _ in $(seq 1 30); do
    pg_isready -h 127.0.0.1 -p "$PGPORT" >/dev/null 2>&1 && break
    sleep 1
  done
fi

echo "==> role + database"
psql -h 127.0.0.1 -p "$PGPORT" -U postgres -tc \
  "SELECT 1 FROM pg_roles WHERE rolname='cogniwork'" | grep -q 1 || \
  psql -h 127.0.0.1 -p "$PGPORT" -U postgres -c \
  "CREATE ROLE cogniwork LOGIN PASSWORD 'cogniwork' SUPERUSER;"
psql -h 127.0.0.1 -p "$PGPORT" -U postgres -tc \
  "SELECT 1 FROM pg_database WHERE datname='cogniwork'" | grep -q 1 || \
  psql -h 127.0.0.1 -p "$PGPORT" -U postgres -c \
  "CREATE DATABASE cogniwork OWNER cogniwork;"

echo "==> migrations"
(cd "$REPO_ROOT/apps/backend" && \
  COGNIWORK_STORE_BACKEND=postgres \
  COGNIWORK_DATABASE_URL="postgresql://cogniwork:cogniwork@127.0.0.1:$PGPORT/cogniwork" \
  COGNIWORK_JWT_SECRET="dev-only-change-me-not-for-production!!" \
  COGNIWORK_IP_HASH_PEPPER="dev-only-change-me" \
  COGNIWORK_VAULT_MASTER_KEY="dev-only-vault-master-key-change-me!!" \
  .venv/bin/python -m cogniwork.migrate)

echo "==> CogniWork install complete."
