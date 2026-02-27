#!/usr/bin/env bash
set -Eeuo pipefail

# TRION/Jarvis safe updater
# - Preflight checks
# - Single-run lock
# - Backup
# - Update + redeploy
# - Health-gated smoke checks
# - Automatic rollback on failure

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${JARVIS_REPO_DIR:-${SCRIPT_DIR}}"
COMPOSE_FILE="${REPO_DIR}/docker-compose.yml"
BRANCH="${JARVIS_BRANCH:-main}"
API_BASE="${TRION_ADMIN_API_BASE:-http://127.0.0.1:8200}"
WEB_BASE="${TRION_WEB_BASE:-http://127.0.0.1:8400}"

LOCK_FILE="${TRION_UPDATE_LOCK_FILE:-/tmp/trion_update.lock}"
BACKUP_ROOT="${TRION_UPDATE_BACKUP_ROOT:-${REPO_DIR}/backups}"

DRY_RUN=0
NO_BACKUP=0
NO_BUILD=0
SKIP_SMOKE=0
ALLOW_DIRTY=0
RESTORE_DATA_ON_ROLLBACK=1

PREV_SHA=""
NEW_SHA=""
BACKUP_DIR=""
ROLLBACK_NEEDED=0
ROLLBACK_ATTEMPTED=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[update]${NC} $*"; }
ok()   { echo -e "${GREEN}[ok]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
err()  { echo -e "${RED}[error]${NC} $*" >&2; }

usage() {
  cat <<USAGE
Usage: $0 [options]

Options:
  --repo-dir <path>         Repository directory (default: script dir)
  --branch <name>           Branch/tag to update to (default: main)
  --no-backup               Skip backups (not recommended)
  --no-build                Skip docker compose build
  --skip-smoke              Skip post-update smoke checks
  --allow-dirty             Allow git working tree with local changes
  --no-rollback-data        Rollback code/services only, no data restore
  --dry-run                 Print actions without changing anything
  -h, --help                Show this help

Examples:
  bash update.sh
  bash update.sh --branch main
  bash update.sh --dry-run
USAGE
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

run_cmd() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '[dry-run]'
    for arg in "$@"; do
      printf ' %q' "$arg"
    done
    printf '\n'
    return 0
  fi
  "$@"
}

DOCKER_PREFIX=()

docker_cmd() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '[dry-run]'
    for arg in "${DOCKER_PREFIX[@]}" docker "$@"; do
      printf ' %q' "$arg"
    done
    printf '\n'
    return 0
  fi
  "${DOCKER_PREFIX[@]}" docker "$@"
}

compose_cmd() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '[dry-run]'
    for arg in "${DOCKER_PREFIX[@]}" docker compose "$@"; do
      printf ' %q' "$arg"
    done
    printf '\n'
    return 0
  fi
  "${DOCKER_PREFIX[@]}" docker compose "$@"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --repo-dir)
        REPO_DIR="$2"; shift 2 ;;
      --branch)
        BRANCH="$2"; shift 2 ;;
      --no-backup)
        NO_BACKUP=1; shift ;;
      --no-build)
        NO_BUILD=1; shift ;;
      --skip-smoke)
        SKIP_SMOKE=1; shift ;;
      --allow-dirty)
        ALLOW_DIRTY=1; shift ;;
      --no-rollback-data)
        RESTORE_DATA_ON_ROLLBACK=0; shift ;;
      --dry-run)
        DRY_RUN=1; shift ;;
      -h|--help)
        usage; exit 0 ;;
      *)
        err "Unknown option: $1"
        usage
        exit 1 ;;
    esac
  done
}

wait_http_ok() {
  local url="$1"
  local timeout_s="$2"
  local step_s=2
  local elapsed=0

  while (( elapsed < timeout_s )); do
    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$step_s"
    elapsed=$((elapsed + step_s))
  done
  return 1
}

ensure_tools() {
  local required=(git docker curl flock tar)
  local cmd
  for cmd in "${required[@]}"; do
    if ! have_cmd "$cmd"; then
      err "Missing required tool: ${cmd}"
      exit 1
    fi
  done
}

ensure_docker_access() {
  if docker info >/dev/null 2>&1; then
    DOCKER_PREFIX=()
    return
  fi

  if have_cmd sudo && sudo docker info >/dev/null 2>&1; then
    DOCKER_PREFIX=(sudo)
    warn "Using sudo for docker commands."
    return
  fi

  if [[ "$DRY_RUN" == "1" ]]; then
    warn "Dry-run: docker daemon not reachable, continuing with simulated commands."
    DOCKER_PREFIX=()
    return
  fi

  err "Docker daemon is not reachable."
  exit 1
}

acquire_lock() {
  if [[ "$DRY_RUN" == "1" ]]; then
    warn "Dry-run: lock acquisition skipped (${LOCK_FILE})"
    return
  fi
  exec 9>"${LOCK_FILE}"
  if ! flock -n 9; then
    err "Another update is already running (lock: ${LOCK_FILE})"
    exit 1
  fi
}

preflight() {
  log "Running preflight checks..."

  [[ -d "$REPO_DIR" ]] || { err "Repo dir not found: $REPO_DIR"; exit 1; }
  [[ -f "$COMPOSE_FILE" ]] || { err "docker-compose.yml not found: $COMPOSE_FILE"; exit 1; }

  if ! git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    err "Not a git repository: $REPO_DIR"
    exit 1
  fi

  if [[ "$ALLOW_DIRTY" == "0" ]]; then
    if [[ -n "$(git -C "$REPO_DIR" status --porcelain 2>/dev/null || true)" ]]; then
      err "Git working tree is dirty. Commit/stash changes first or use --allow-dirty."
      exit 1
    fi
  fi

  compose_cmd -f "$COMPOSE_FILE" version >/dev/null
  compose_cmd -f "$COMPOSE_FILE" config -q >/dev/null

  PREV_SHA="$(git -C "$REPO_DIR" rev-parse HEAD)"
  ok "Preflight OK (sha=${PREV_SHA:0:12})"
}

backup_host_dir() {
  local src="$1"
  local archive_name="$2"

  if [[ ! -d "$src" ]]; then
    warn "Host dir not found, skipping backup: $src"
    return 0
  fi

  run_cmd mkdir -p "$BACKUP_DIR/host"
  run_cmd tar -C "$src" -czf "$BACKUP_DIR/host/${archive_name}.tgz" .
}

backup_volume_from_container() {
  local container="$1"
  local mount_path="$2"
  local archive_name="$3"

  if ! docker_cmd ps -a --format '{{.Names}}' | grep -qx "$container"; then
    warn "Container not found, skipping volume backup: ${container}:${mount_path}"
    return 0
  fi

  run_cmd mkdir -p "$BACKUP_DIR/volumes"
  docker_cmd run --rm \
    --volumes-from "$container" \
    -v "$BACKUP_DIR/volumes:/backup" \
    busybox:1.36 \
    sh -lc "tar -czf /backup/${archive_name}.tgz -C ${mount_path} ."
}

create_backup() {
  if [[ "$NO_BACKUP" == "1" ]]; then
    warn "Backup disabled (--no-backup)."
    return
  fi

  local ts
  ts="$(date +%Y%m%d-%H%M%S)"
  BACKUP_DIR="${BACKUP_ROOT}/update-${ts}"

  log "Creating backup in ${BACKUP_DIR}"
  run_cmd mkdir -p "$BACKUP_DIR"

  run_cmd bash -lc "cat > '$BACKUP_DIR/meta.txt' <<META
repo_dir=${REPO_DIR}
prev_sha=${PREV_SHA}
branch=${BRANCH}
created_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
META"

  if [[ -f "$REPO_DIR/.env" ]]; then
    run_cmd cp "$REPO_DIR/.env" "$BACKUP_DIR/.env.bak"
  fi

  backup_host_dir "$REPO_DIR/memory" "memory"
  backup_host_dir "$REPO_DIR/memory_speicher" "memory_speicher"

  backup_volume_from_container "mcp-sql-memory" "/app/data" "memory_data"
  backup_volume_from_container "jarvis-admin-api" "/app/data" "commander_data"
  backup_volume_from_container "jarvis-admin-api" "/trion-home" "trion_home"

  ok "Backup finished."
}

restore_host_backup() {
  local archive="$1"
  local target_dir="$2"

  [[ -f "$archive" ]] || return 0
  run_cmd mkdir -p "$target_dir"
  run_cmd rm -rf "$target_dir"/*
  run_cmd tar -xzf "$archive" -C "$target_dir"
}

restore_volume_backup() {
  local container="$1"
  local mount_path="$2"
  local archive="$3"

  [[ -f "$archive" ]] || return 0

  if ! docker_cmd ps -a --format '{{.Names}}' | grep -qx "$container"; then
    warn "Container missing for restore, skipping ${container}:${mount_path}"
    return 0
  fi

  docker_cmd run --rm \
    --volumes-from "$container" \
    -v "$(dirname "$archive"):/backup" \
    busybox:1.36 \
    sh -lc "mkdir -p '${mount_path}' && rm -rf '${mount_path}'/* && tar -xzf /backup/$(basename "$archive") -C '${mount_path}'"
}

restore_backup_data() {
  if [[ "$NO_BACKUP" == "1" || "$RESTORE_DATA_ON_ROLLBACK" == "0" ]]; then
    warn "Rollback data restore skipped."
    return
  fi
  if [[ -z "$BACKUP_DIR" || ! -d "$BACKUP_DIR" ]]; then
    warn "No backup directory found for restore."
    return
  fi

  log "Restoring backup data from ${BACKUP_DIR}"
  restore_host_backup "$BACKUP_DIR/host/memory.tgz" "$REPO_DIR/memory"
  restore_host_backup "$BACKUP_DIR/host/memory_speicher.tgz" "$REPO_DIR/memory_speicher"

  restore_volume_backup "mcp-sql-memory" "/app/data" "$BACKUP_DIR/volumes/memory_data.tgz"
  restore_volume_backup "jarvis-admin-api" "/app/data" "$BACKUP_DIR/volumes/commander_data.tgz"
  restore_volume_backup "jarvis-admin-api" "/trion-home" "$BACKUP_DIR/volumes/trion_home.tgz"
}

update_git() {
  log "Updating git repository..."
  run_cmd git -C "$REPO_DIR" fetch --all --prune

  if git -C "$REPO_DIR" show-ref --verify --quiet "refs/heads/${BRANCH}"; then
    run_cmd git -C "$REPO_DIR" checkout "$BRANCH"
  else
    run_cmd git -C "$REPO_DIR" checkout -B "$BRANCH" "origin/$BRANCH"
  fi

  run_cmd git -C "$REPO_DIR" pull --ff-only origin "$BRANCH"
  NEW_SHA="$(git -C "$REPO_DIR" rev-parse HEAD)"

  if [[ "$PREV_SHA" == "$NEW_SHA" ]]; then
    warn "No code changes detected (already up-to-date)."
  else
    ok "Updated ${PREV_SHA:0:12} -> ${NEW_SHA:0:12}"
  fi
}

deploy_stack() {
  log "Deploying stack..."

  if [[ "$NO_BUILD" == "0" ]]; then
    compose_cmd -f "$COMPOSE_FILE" build
  else
    warn "Skipping build (--no-build)."
  fi

  compose_cmd -f "$COMPOSE_FILE" up -d
  ok "Stack started."
}

run_smoke_checks() {
  if [[ "$DRY_RUN" == "1" ]]; then
    warn "Dry-run: skipping smoke checks."
    return
  fi

  if [[ "$SKIP_SMOKE" == "1" ]]; then
    warn "Skipping smoke checks (--skip-smoke)."
    return
  fi

  log "Running smoke checks..."

  if ! wait_http_ok "${API_BASE}/health" 120; then
    err "Smoke failed: ${API_BASE}/health unreachable"
    return 1
  fi

  if ! wait_http_ok "${API_BASE}/api/settings/" 90; then
    err "Smoke failed: ${API_BASE}/api/settings/ unreachable"
    return 1
  fi

  if ! wait_http_ok "${WEB_BASE}" 60; then
    warn "Web UI did not respond in time: ${WEB_BASE}"
  fi

  ok "Smoke checks passed."
}

rollback() {
  ROLLBACK_ATTEMPTED=1
  set +e

  err "Update failed - starting rollback..."

  if [[ -n "$PREV_SHA" ]]; then
    log "Restoring git SHA ${PREV_SHA:0:12}"
    git -C "$REPO_DIR" reset --hard "$PREV_SHA" >/dev/null 2>&1 || err "Failed to reset git to previous SHA"
  fi

  restore_backup_data

  if [[ "$NO_BUILD" == "0" ]]; then
    compose_cmd -f "$COMPOSE_FILE" build >/dev/null 2>&1 || err "Rollback build failed"
  fi
  compose_cmd -f "$COMPOSE_FILE" up -d >/dev/null 2>&1 || err "Rollback stack start failed"

  if wait_http_ok "${API_BASE}/health" 90; then
    ok "Rollback completed and admin API is healthy."
  else
    err "Rollback finished, but admin API is still unhealthy. Manual check required."
  fi

  set -e
}

on_err() {
  local exit_code=$?
  local line_no=${1:-unknown}

  err "Failure at line ${line_no} (exit=${exit_code})"

  if [[ "$DRY_RUN" == "0" && "$ROLLBACK_NEEDED" == "1" && "$ROLLBACK_ATTEMPTED" == "0" ]]; then
    rollback || true
  fi

  exit "$exit_code"
}

main() {
  parse_args "$@"
  trap 'on_err ${LINENO}' ERR

  ensure_tools
  ensure_docker_access
  acquire_lock
  preflight
  create_backup

  ROLLBACK_NEEDED=1

  update_git
  deploy_stack
  run_smoke_checks

  ROLLBACK_NEEDED=0
  ok "Update finished successfully."

  if [[ -n "$BACKUP_DIR" ]]; then
    log "Backup kept at: ${BACKUP_DIR}"
  fi
  log "Current SHA: $(git -C "$REPO_DIR" rev-parse --short HEAD)"
}

main "$@"
