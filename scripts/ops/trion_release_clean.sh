#!/usr/bin/env bash
# ============================================================
# scripts/ops/trion_release_clean.sh — TRION Release Clean
# ============================================================
# Goal:
#   One-command developer clean for release-ready baseline:
#     1) hard live restore (runtime/user data wipe + defaults)
#     2) prune user skills (keep only core skills from manifest)
#     3) restart critical services
#     4) optional quick diagnose
#
# Safety:
#   - lock file prevents parallel runs
#   - supports --plan and --dry-run
#   - non-interactive mode via --yes --non-interactive
# ============================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker-compose.yml"
LIVE_RESTORE_SCRIPT="${SCRIPT_DIR}/trion_live_restore.sh"
DIAG_SCRIPT="${SCRIPT_DIR}/trion_diagnose.sh"
MANIFEST_PATH="${RESTORE_MANIFEST_PATH:-${REPO_ROOT}/seed/restore_manifest.json}"
SHARED_SKILLS_DIR="${TRION_SHARED_SKILLS_DIR:-/DATA/AppData/MCP/Jarvis/shared_skills}"
LOCK_FILE="${TRION_RELEASE_CLEAN_LOCK_FILE:-${REPO_ROOT}/memory_speicher/trion_release_clean.lock}"

OPT_DRY_RUN=false
OPT_PLAN=false
OPT_YES=false
OPT_NON_INTERACTIVE=false
OPT_SKIP_SMOKE=false
OPT_SKIP_DIAGNOSE=false
OPT_SKIP_SKILL_PRUNE=false
OPT_SKIP_SERVICE_RESTART=false
OPT_KEEP_DIGEST_WORKER=false
OPT_KEEP_PROTOCOL=false
OPT_KEEP_CSV=false
OPT_SKIP_HOME_START=false
OPT_PAUSE_ADMIN=true

log()  { echo -e "${CYAN}[TRION-RELEASE-CLEAN]${NC} $*"; }
ok()   { echo -e "  ${GREEN}OK${NC} $*"; }
warn() { echo -e "  ${YELLOW}WARN${NC} $*"; }
err()  { echo -e "  ${RED}ERR${NC} $*" >&2; }

usage() {
  cat <<'USAGE'
Usage: scripts/ops/trion_release_clean.sh [OPTIONS]

Core behavior:
  - hard live restore with defaults reseed
  - prune shared_skills to core skills from restore manifest
  - restart critical services
  - optional quick diagnose

Options:
  --plan                 Print plan and exit
  --dry-run              Print actions only (no writes)
  --yes                  Skip confirmations in delegated scripts
  --non-interactive      Non-prompt mode (requires --yes)
  --skip-smoke           Skip restore smoke test
  --skip-diagnose        Skip final quick diagnose
  --skip-skill-prune     Do not prune user skills
  --skip-service-restart Do not restart services after prune
  --keep-digest-worker   Do not pause digest-worker during restore
  --keep-protocol        Keep memory/*.md protocol files (hard restore)
  --keep-csv             Keep memory_speicher/*.csv + digest state/lock
  --skip-home-start      Do not auto-start TRION home container
  --no-pause-admin       Keep admin API running during restore
  --manifest <path>      Override restore manifest path
  --shared-skills-dir <path>
                         Override shared skills path
  -h, --help             Show this help

Examples:
  bash scripts/ops/trion_release_clean.sh --plan
  bash scripts/ops/trion_release_clean.sh --dry-run --yes --non-interactive
  bash scripts/ops/trion_release_clean.sh --yes --non-interactive
USAGE
}

do_cmd() {
  if $OPT_DRY_RUN; then
    echo -e "  ${DIM}[dry-run] $*${NC}"
    return 0
  fi
  "$@"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --plan) OPT_PLAN=true; shift ;;
      --dry-run) OPT_DRY_RUN=true; shift ;;
      --yes) OPT_YES=true; shift ;;
      --non-interactive) OPT_NON_INTERACTIVE=true; shift ;;
      --skip-smoke) OPT_SKIP_SMOKE=true; shift ;;
      --skip-diagnose) OPT_SKIP_DIAGNOSE=true; shift ;;
      --skip-skill-prune) OPT_SKIP_SKILL_PRUNE=true; shift ;;
      --skip-service-restart) OPT_SKIP_SERVICE_RESTART=true; shift ;;
      --keep-digest-worker) OPT_KEEP_DIGEST_WORKER=true; shift ;;
      --keep-protocol) OPT_KEEP_PROTOCOL=true; shift ;;
      --keep-csv) OPT_KEEP_CSV=true; shift ;;
      --skip-home-start) OPT_SKIP_HOME_START=true; shift ;;
      --no-pause-admin) OPT_PAUSE_ADMIN=false; shift ;;
      --manifest) MANIFEST_PATH="$2"; shift 2 ;;
      --shared-skills-dir) SHARED_SKILLS_DIR="$2"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *)
        err "Unknown option: $1"
        usage
        exit 1
        ;;
    esac
  done

  if $OPT_NON_INTERACTIVE && ! $OPT_YES; then
    err "--non-interactive requires --yes."
    exit 2
  fi
}

print_plan() {
  echo -e "${BOLD}TRION Release Clean Plan${NC}"
  echo "repo_root: ${REPO_ROOT}"
  echo "manifest: ${MANIFEST_PATH}"
  echo "shared_skills_dir: ${SHARED_SKILLS_DIR}"
  echo "phases:"
  echo "  1) hard live restore (reseed blueprints + core skills)"
  echo "  2) prune shared skills to core skill set from manifest"
  echo "  3) restart services: skill-server, tool-executor, jarvis-admin-api"
  echo "  4) quick diagnose (--quick)"
}

acquire_lock() {
  if $OPT_DRY_RUN; then
    warn "dry-run: lock skipped (${LOCK_FILE})"
    return
  fi
  mkdir -p "$(dirname "${LOCK_FILE}")"
  exec 9>"${LOCK_FILE}"
  if ! flock -n 9; then
    err "Another release clean is running (lock: ${LOCK_FILE})"
    exit 3
  fi
}

run_live_restore() {
  local args=(
    --hard
    --reseed-blueprints
    --reseed-skills
  )

  if ! $OPT_SKIP_SMOKE; then
    args+=(--smoke-test)
  fi
  if $OPT_KEEP_DIGEST_WORKER; then
    args+=(--keep-digest-worker)
  fi
  if $OPT_KEEP_PROTOCOL; then
    args+=(--keep-protocol)
  fi
  if $OPT_KEEP_CSV; then
    args+=(--keep-csv)
  fi
  if $OPT_SKIP_HOME_START; then
    args+=(--skip-home-start)
  fi
  if $OPT_PAUSE_ADMIN; then
    args+=(--pause-admin)
  fi
  if $OPT_DRY_RUN; then
    args+=(--dry-run)
  fi
  if $OPT_YES; then
    args+=(--yes)
  fi
  if $OPT_NON_INTERACTIVE; then
    args+=(--non-interactive)
  fi

  log "Phase 1: hard live restore"
  do_cmd bash "${LIVE_RESTORE_SCRIPT}" "${args[@]}"
}

prune_skills() {
  if $OPT_SKIP_SKILL_PRUNE; then
    warn "Phase 2: skill prune skipped (--skip-skill-prune)"
    return
  fi

  log "Phase 2: prune shared skills to core set"

  if [[ ! -f "${MANIFEST_PATH}" ]]; then
    err "Manifest not found: ${MANIFEST_PATH}"
    exit 2
  fi

  local dry_flag="0"
  $OPT_DRY_RUN && dry_flag="1"

  do_cmd python3 - "${MANIFEST_PATH}" "${SHARED_SKILLS_DIR}" "${dry_flag}" <<'PY'
import datetime
import json
import os
import shutil
import sys

manifest_path = sys.argv[1]
skills_dir = sys.argv[2]
dry_run = sys.argv[3] == "1"

with open(manifest_path, "r", encoding="utf-8") as f:
    manifest = json.load(f)

core_items = manifest.get("core_skills", [])
core_meta = {}
for item in core_items:
    if isinstance(item, dict):
        name = str(item.get("name", "")).strip()
        version = str(item.get("version", "1.0.0")).strip() or "1.0.0"
        description = str(item.get("description", "")).strip()
    else:
        name = str(item).strip()
        version = "1.0.0"
        description = ""
    if name:
        core_meta[name] = {"version": version, "description": description}

os.makedirs(skills_dir, exist_ok=True)
entries = sorted(os.listdir(skills_dir))

removed = []
kept = []
for name in entries:
    if name == "_registry":
        continue
    path = os.path.join(skills_dir, name)
    if name in core_meta:
        kept.append(name)
        continue
    removed.append(name)
    if not dry_run:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

registry_dir = os.path.join(skills_dir, "_registry")
registry_path = os.path.join(registry_dir, "installed.json")
installed = {}
now = datetime.datetime.now(datetime.timezone.utc).isoformat()

for name, meta in sorted(core_meta.items()):
    skill_path = os.path.join(skills_dir, name)
    if os.path.isdir(skill_path):
        installed[name] = {
            "version": meta["version"],
            "installed_at": now,
            "description": meta["description"],
            "triggers": [],
        }

if dry_run:
    print(f"[dry-run] would remove {len(removed)} non-core entries: {removed}")
    print(f"[dry-run] would keep {len(kept)} core entries: {kept}")
    print(f"[dry-run] would write registry entries: {sorted(installed.keys())}")
else:
    os.makedirs(registry_dir, exist_ok=True)
    tmp_path = registry_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(installed, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, registry_path)
    print(f"removed_non_core={len(removed)}")
    print(f"kept_core={len(kept)}")
    print(f"registry_entries={len(installed)}")
    if removed:
        print("removed_names=" + ",".join(removed))
PY
}

restart_services() {
  if $OPT_SKIP_SERVICE_RESTART; then
    warn "Phase 3: service restart skipped (--skip-service-restart)"
    return
  fi
  log "Phase 3: restart core services"
  do_cmd docker compose -f "${COMPOSE_FILE}" restart skill-server tool-executor jarvis-admin-api
}

run_diagnose() {
  if $OPT_SKIP_DIAGNOSE; then
    warn "Phase 4: diagnose skipped (--skip-diagnose)"
    return
  fi
  log "Phase 4: quick diagnose"
  do_cmd bash "${DIAG_SCRIPT}" --quick
}

main() {
  parse_args "$@"

  if $OPT_PLAN; then
    print_plan
    exit 0
  fi

  if [[ ! -f "${LIVE_RESTORE_SCRIPT}" ]]; then
    err "Missing script: ${LIVE_RESTORE_SCRIPT}"
    exit 2
  fi
  if [[ ! -f "${DIAG_SCRIPT}" ]]; then
    err "Missing script: ${DIAG_SCRIPT}"
    exit 2
  fi
  if [[ ! -f "${COMPOSE_FILE}" ]]; then
    err "Missing compose file: ${COMPOSE_FILE}"
    exit 2
  fi

  acquire_lock

  echo ""
  echo -e "${BOLD}TRION Release Clean${NC}"
  echo "repo: ${REPO_ROOT}"
  echo "manifest: ${MANIFEST_PATH}"
  echo "shared_skills: ${SHARED_SKILLS_DIR}"
  echo ""

  run_live_restore
  prune_skills
  restart_services
  run_diagnose

  ok "Release clean completed."
}

main "$@"
