#!/usr/bin/env bash
# CogniWork Cloud Agent — per-boot service reconciliation. Idempotent.
# Brings up PostgreSQL and Redis (used by the production store path and
# integration tests). The default backend dev server uses the in-memory store
# and does not require these, but they are started so the full stack is ready.
set -euo pipefail

export PATH="/usr/lib/postgresql/16/bin:$HOME/.local/bin:$PATH"
PGDATA="$HOME/.local/share/cogniwork/pgdata"
PGPORT=5432

if pg_isready -h 127.0.0.1 -p "$PGPORT" >/dev/null 2>&1; then
  echo "postgres: already running"
else
  # pg_ctl clears a stale postmaster.pid left by a snapshot on its own.
  pg_ctl -D "$PGDATA" -o "-p $PGPORT -k /tmp" -l "$HOME/.local/share/cogniwork/pg.log" start
fi

if redis-cli -p 6379 ping >/dev/null 2>&1; then
  echo "redis: already running"
else
  redis-server --daemonize yes --port 6379 --dir /tmp
fi

for _ in $(seq 1 30); do
  pg_isready -h 127.0.0.1 -p "$PGPORT" >/dev/null 2>&1 && break
  sleep 1
done
pg_isready -h 127.0.0.1 -p "$PGPORT" && echo "postgres: ready"
redis-cli -p 6379 ping >/dev/null 2>&1 && echo "redis: ready"
echo "CogniWork services ready."
