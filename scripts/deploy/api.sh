#!/usr/bin/env bash
# pm2 entrypoint for cogniwork-api (docs/deploy.md §6.4).
# Secrets live in /etc/cogniwork/env (mode 640, group cogniwork) — not in ecosystem config.
set -euo pipefail
set -a
# shellcheck disable=SC1091
. /etc/cogniwork/env
set +a
cd /opt/cogniwork/apps/backend
# exec so uvicorn is the PID pm2 manages (restart must not orphan Python under a dead shell)
exec .venv/bin/python -m uvicorn cogniwork.main:app \
  --host 127.0.0.1 --port 8000 --workers 1
