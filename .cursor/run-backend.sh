#!/usr/bin/env bash
# CogniWork backend dev server.
#
# Defaults to the in-memory store — the documented local default (see
# apps/backend/README.md). It boots with zero external services and runs the
# full zero-auth core path (register -> upload xlsx -> task -> artifact ->
# download). To use the production path instead, export
# COGNIWORK_STORE_BACKEND=postgres before this runs; PostgreSQL and Redis are
# already provisioned by start.sh at the URLs defaulted below.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.local/bin:$PATH"
cd "$REPO_ROOT/apps/backend"

export COGNIWORK_STORE_BACKEND="${COGNIWORK_STORE_BACKEND:-memory}"
export COGNIWORK_DATABASE_URL="${COGNIWORK_DATABASE_URL:-postgresql://cogniwork:cogniwork@127.0.0.1:5432/cogniwork}"
export COGNIWORK_REDIS_URL="${COGNIWORK_REDIS_URL:-redis://127.0.0.1:6379/0}"
export COGNIWORK_LLM_PROVIDER="${COGNIWORK_LLM_PROVIDER:-auto}"
export COGNIWORK_OAUTH_STUB="${COGNIWORK_OAUTH_STUB:-true}"
# Dev-only placeholders (mirror .env.example). Never use in production.
export COGNIWORK_JWT_SECRET="${COGNIWORK_JWT_SECRET:-dev-only-change-me-not-for-production!!}"
export COGNIWORK_IP_HASH_PEPPER="${COGNIWORK_IP_HASH_PEPPER:-dev-only-change-me}"
export COGNIWORK_VAULT_MASTER_KEY="${COGNIWORK_VAULT_MASTER_KEY:-dev-only-vault-master-key-change-me!!}"

exec .venv/bin/python -m uvicorn cogniwork.main:app --host 0.0.0.0 --port 8000 --reload
