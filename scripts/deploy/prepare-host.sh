#!/usr/bin/env bash
# Host preparation for CogniWork production (docs/deploy.md §6.1 / §6.2).
# Debian/Ubuntu only. Run as root (or via sudo). Idempotent where practical.
#
# Usage:
#   sudo ./scripts/deploy/prepare-host.sh
#   sudo ./scripts/deploy/prepare-host.sh --with-db
#   sudo COGNIWORK_DB_PASSWORD='…' ./scripts/deploy/prepare-host.sh --with-db
#
# Does not: clone the repo, write secrets into /etc/cogniwork/env, run migrations,
# or start pm2. Those need an operator and come after (§6.3–§6.4).

set -euo pipefail

APP_USER=cogniwork
APP_HOME=/opt/cogniwork
APP_LOG=/var/log/cogniwork
APP_ETC=/etc/cogniwork
APP_BIN="${APP_HOME}/bin"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

WITH_DB=0
SKIP_TOOLCHAIN=0

usage() {
  cat <<'EOF'
Usage: prepare-host.sh [options]

  (default)     Create service account + dirs; install Python 3.12, uv, Node 22, pm2, pnpm
  --with-db     Also install PostgreSQL 16 + Redis 7 and create role/db (same-host)
  --skip-toolchain
                Only account + dirs (and --with-db if set); skip language runtimes
  -h, --help    Show this help

Environment:
  COGNIWORK_DB_PASSWORD   Password for the cogniwork Postgres role when --with-db.
                          If unset, prompts interactively (needs a TTY).
EOF
}

log() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

require_root() {
  [[ "$(id -u)" -eq 0 ]] || die "run as root (sudo $0 …)"
}

require_debian() {
  [[ -f /etc/os-release ]] || die "cannot detect OS (/etc/os-release missing)"
  # shellcheck source=/dev/null
  . /etc/os-release
  case "${ID:-}" in
    debian|ubuntu) ;;
    *) die "this script targets Debian/Ubuntu only (got ID=${ID:-unknown}). See docs/deploy.md §6.1 for RHEL notes." ;;
  esac
  CODENAME="${VERSION_CODENAME:-}"
  [[ -n "$CODENAME" ]] || die "VERSION_CODENAME empty in /etc/os-release"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --with-db) WITH_DB=1 ;;
      --skip-toolchain) SKIP_TOOLCHAIN=1 ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown option: $1 (try --help)" ;;
    esac
    shift
  done
}

ensure_user_and_dirs() {
  log "service account and directories"
  if ! id -u "$APP_USER" >/dev/null 2>&1; then
    useradd --system --home "$APP_HOME" --shell /usr/sbin/nologin "$APP_USER"
  else
    log "user $APP_USER already exists"
  fi

  install -d -o "$APP_USER" -g "$APP_USER" "$APP_HOME" "$APP_LOG"
  # Startup wrapper: root owns, service account executes only.
  install -d -o root -g root "$APP_BIN"
  # Env file lives here: service account can read, not write.
  install -d -m 750 -o root -g "$APP_USER" "$APP_ETC"

  if [[ ! -e "${APP_ETC}/env" ]]; then
    install -m 640 -o root -g "$APP_USER" /dev/null "${APP_ETC}/env"
    log "created empty ${APP_ETC}/env (fill §4 vars before starting API)"
  fi
}

install_wrapper_templates() {
  log "install api wrapper + pm2 ecosystem templates"
  install -m 755 -o root -g root "${SCRIPT_DIR}/api.sh" "${APP_BIN}/api.sh"
  install -m 644 -o root -g "$APP_USER" \
    "${SCRIPT_DIR}/ecosystem.config.cjs" "${APP_ETC}/ecosystem.config.cjs"
}

install_toolchain() {
  log "apt update + build tools / Python 3.12"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y curl ca-certificates python3.12 python3.12-venv build-essential

  if ! command -v uv >/dev/null 2>&1; then
    log "install uv into /usr/local/bin (service account has no home bin)"
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
  else
    log "uv already present: $(command -v uv)"
  fi

  if ! command -v node >/dev/null 2>&1 || ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) < 22)'; then
    log "install Node.js 22 (Nodesource)"
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -y nodejs
  else
    log "Node.js already >= 22: $(node -v)"
  fi

  log "global pm2 + pnpm"
  npm i -g pm2 pnpm
}

install_postgres_redis() {
  log "PostgreSQL 16 (PGDG) + Redis"
  export DEBIAN_FRONTEND=noninteractive
  apt-get install -y curl ca-certificates
  install -d /usr/share/postgresql-common/pgdg
  curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    https://www.postgresql.org/media/keys/ACCC4CF8.asc
  echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
https://apt.postgresql.org/pub/repos/apt ${CODENAME}-pgdg main" \
    > /etc/apt/sources.list.d/pgdg.list
  apt-get update -y
  apt-get install -y postgresql-16 redis-server
  systemctl enable --now postgresql redis-server
}

psql_as_postgres() {
  sudo -u postgres psql -v ON_ERROR_STOP=1 "$@"
}

ensure_db_role() {
  local password
  if [[ -n "${COGNIWORK_DB_PASSWORD:-}" ]]; then
    password="$COGNIWORK_DB_PASSWORD"
  elif [[ -t 0 ]]; then
    read -r -s -p "Password for Postgres role '${APP_USER}': " password
    echo
    [[ -n "$password" ]] || die "empty password"
  else
    die "set COGNIWORK_DB_PASSWORD or run interactively when using --with-db"
  fi

  # Role must own the DB so LangGraph PostgresSaver.setup() can create checkpoints*.
  # :'pass' is psql's SQL-literal expansion — safe with any password characters.
  if psql_as_postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='${APP_USER}'" | grep -q 1; then
    log "Postgres role ${APP_USER} exists; updating password"
    psql_as_postgres -v pass="$password" <<SQL
ALTER ROLE ${APP_USER} WITH LOGIN PASSWORD :'pass';
SQL
  else
    log "create Postgres role ${APP_USER}"
    psql_as_postgres -v pass="$password" <<SQL
CREATE ROLE ${APP_USER} LOGIN PASSWORD :'pass';
SQL
  fi

  if psql_as_postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${APP_USER}'" | grep -q 1; then
    log "database ${APP_USER} already exists"
    psql_as_postgres -c "ALTER DATABASE ${APP_USER} OWNER TO ${APP_USER}"
  else
    log "create database ${APP_USER}"
    sudo -u postgres createdb --owner="$APP_USER" "$APP_USER"
  fi
}

print_next_steps() {
  cat <<EOF

Host prep done.

Next (manual):
  1. Put the repo (or release tree) under ${APP_HOME}
     Backend venv path expected by migrate / pm2: ${APP_HOME}/apps/backend/.venv
  2. Edit ${APP_ETC}/env with production values (docs/deploy.md §4)
  3. As ${APP_USER}: create venv, install deps, run migrate (§6.3)
  4. pm2 start ${APP_ETC}/ecosystem.config.cjs as ${APP_USER}; pm2 save; pm2 startup (§6.4)
  5. Build/sync web dist + nginx (§6.5 / §6.6)

Wrappers installed:
  ${APP_BIN}/api.sh
  ${APP_ETC}/ecosystem.config.cjs
EOF
}

main() {
  parse_args "$@"
  require_root
  require_debian
  ensure_user_and_dirs
  install_wrapper_templates
  if [[ "$SKIP_TOOLCHAIN" -eq 0 ]]; then
    install_toolchain
  else
    log "skipping toolchain (--skip-toolchain)"
  fi
  if [[ "$WITH_DB" -eq 1 ]]; then
    install_postgres_redis
    ensure_db_role
  else
    log "skipping Postgres/Redis (pass --with-db for same-host install; use managed instances otherwise)"
  fi
  print_next_steps
}

main "$@"
