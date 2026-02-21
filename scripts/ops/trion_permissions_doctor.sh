#!/usr/bin/env bash
# ============================================================
# scripts/ops/trion_permissions_doctor.sh — TRION Permissions Doctor
# ============================================================
# Checks and optionally fixes common permission issues for TRION ops scripts.
#
# Modes:
#   --check (default)  : diagnostics only
#   --fix-safe         : safe local fixes within repo (mkdir/chmod/chown if root)
#   --fix-docker       : include docker access diagnostics and fix hints
#   --dry-run          : print fix actions, do not modify files
#   --yes              : skip interactive confirmation for fix modes
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

CURRENT_USER="$(id -un)"
CURRENT_GROUP="$(id -gn)"
IS_ROOT=false
[ "$(id -u)" -eq 0 ] && IS_ROOT=true

TARGET_DIRS=(
  "memory"
  "memory_speicher"
  "logs"
  "scripts/ops"
  "seed"
)

LOCK_FILES=(
  "memory_speicher/trion_restore.lock"
  "memory_speicher/trion_live_restore.lock"
)

PROBE_FILE_SUFFIX=".perm_doctor_probe.$$"

OPT_FIX_SAFE=false
OPT_FIX_DOCKER=false
OPT_DRY_RUN=false
OPT_YES=false

for arg in "$@"; do
  case "$arg" in
    --check) ;;
    --fix-safe) OPT_FIX_SAFE=true ;;
    --fix-docker) OPT_FIX_DOCKER=true ;;
    --dry-run) OPT_DRY_RUN=true ;;
    --yes) OPT_YES=true ;;
    -h|--help)
      cat <<'EOF'
Usage: scripts/ops/trion_permissions_doctor.sh [OPTIONS]

Options:
  --check        Diagnostics only (default)
  --fix-safe     Apply safe local fixes inside repo paths
  --fix-docker   Include Docker permission diagnostics and fix hints
  --dry-run      Print fix actions without modifying files
  --yes          Skip confirmation prompt in fix mode
  -h, --help     Show this help

Examples:
  bash scripts/ops/trion_permissions_doctor.sh --check
  bash scripts/ops/trion_permissions_doctor.sh --fix-safe
  bash scripts/ops/trion_permissions_doctor.sh --fix-safe --fix-docker
  bash scripts/ops/trion_permissions_doctor.sh --fix-safe --dry-run
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

log()  { echo -e "${CYAN}[PERM-DOCTOR]${NC} $*"; }
ok()   { echo -e "  ${GREEN}OK${NC} $*"; }
warn() { echo -e "  ${YELLOW}WARN${NC} $*"; }
err()  { echo -e "  ${RED}ERR${NC} $*"; }
note() { echo -e "  ${DIM}→${NC} $*"; }

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

inc_pass() { PASS_COUNT=$((PASS_COUNT + 1)); }
inc_warn() { WARN_COUNT=$((WARN_COUNT + 1)); }
inc_fail() { FAIL_COUNT=$((FAIL_COUNT + 1)); }

path_guard_within_repo() {
  local rp
  rp="$(realpath -m "$1" 2>/dev/null || true)"
  [ -n "${rp}" ] || return 1
  case "${rp}" in
    "${REPO_ROOT}"|${REPO_ROOT}/*) return 0 ;;
    *) return 1 ;;
  esac
}

run_or_dry() {
  if $OPT_DRY_RUN; then
    echo -e "  ${DIM}[dry-run] $*${NC}"
    return 0
  fi
  "$@"
}

probe_write() {
  local dir="$1"
  local probe="${dir}/${PROBE_FILE_SUFFIX}"
  if $OPT_DRY_RUN; then
    # Dry-run avoids write side effects; rely on -w check only.
    [ -w "${dir}" ]
    return $?
  fi
  if ! : > "${probe}" 2>/dev/null; then
    return 1
  fi
  rm -f "${probe}" 2>/dev/null || true
  return 0
}

fix_dir_permissions() {
  local p="$1"
  if ! $OPT_FIX_SAFE; then
    return 0
  fi
  run_or_dry chmod u+rwx "${p}" || true
  run_or_dry chmod g+rwx "${p}" || true
  if $IS_ROOT; then
    run_or_dry chown "${CURRENT_USER}:${CURRENT_GROUP}" "${p}" || true
  fi
}

check_directory() {
  local rel="$1"
  local abs="${REPO_ROOT}/${rel}"

  if ! path_guard_within_repo "${abs}"; then
    err "Path guard rejected ${abs}"
    inc_fail
    return
  fi

  if [ ! -e "${abs}" ]; then
    if $OPT_FIX_SAFE; then
      warn "Missing directory ${rel}, creating it"
      inc_warn
      run_or_dry mkdir -p "${abs}" || true
    else
      err "Missing directory ${rel}"
      inc_fail
      return
    fi
  fi

  if [ ! -d "${abs}" ]; then
    err "Path is not a directory: ${rel}"
    inc_fail
    return
  fi

  local owner group
  owner="$(stat -c '%U' "${abs}" 2>/dev/null || echo '?')"
  group="$(stat -c '%G' "${abs}" 2>/dev/null || echo '?')"

  if [ "${owner}" != "${CURRENT_USER}" ]; then
    warn "${rel}: owner=${owner} (expected ${CURRENT_USER})"
    inc_warn
    fix_dir_permissions "${abs}"
  fi

  if ! probe_write "${abs}"; then
    warn "${rel}: not writable"
    inc_warn
    fix_dir_permissions "${abs}"
  fi

  if probe_write "${abs}"; then
    ok "${rel}: writable (owner=${owner}, group=${group})"
    inc_pass
  else
    err "${rel}: still not writable after checks/fixes"
    inc_fail
  fi
}

check_lock_file() {
  local rel="$1"
  local abs="${REPO_ROOT}/${rel}"
  local parent
  parent="$(dirname "${abs}")"

  if ! path_guard_within_repo "${parent}"; then
    err "Path guard rejected lock parent ${parent}"
    inc_fail
    return
  fi

  if [ ! -d "${parent}" ]; then
    if $OPT_FIX_SAFE; then
      warn "Missing lock parent ${parent}, creating it"
      inc_warn
      run_or_dry mkdir -p "${parent}" || true
    else
      err "Missing lock parent ${parent}"
      inc_fail
      return
    fi
  fi

  if [ -e "${abs}" ] && [ ! -w "${abs}" ]; then
    warn "Lock file not writable: ${rel}"
    inc_warn
    if $OPT_FIX_SAFE; then
      run_or_dry chmod u+rw "${abs}" || true
      if $IS_ROOT; then
        run_or_dry chown "${CURRENT_USER}:${CURRENT_GROUP}" "${abs}" || true
      fi
    fi
  fi

  if probe_write "${parent}"; then
    ok "Lock parent writable: ${rel}"
    inc_pass
  else
    err "Lock parent still not writable: ${rel}"
    inc_fail
  fi
}

check_ops_scripts() {
  local ops_dir="${REPO_ROOT}/scripts/ops"
  if [ ! -d "${ops_dir}" ]; then
    err "scripts/ops missing"
    inc_fail
    return
  fi

  local any=false
  for f in "${ops_dir}"/*.sh; do
    [ -e "${f}" ] || continue
    any=true
    local rel
    rel="$(realpath --relative-to="${REPO_ROOT}" "${f}")"
    if [ ! -x "${f}" ]; then
      warn "${rel}: not executable"
      inc_warn
      if $OPT_FIX_SAFE; then
        run_or_dry chmod u+x "${f}" || true
      fi
    fi
    if [ ! -x "${f}" ]; then
      err "${rel}: still not executable"
      inc_fail
    else
      ok "${rel}: executable"
      inc_pass
    fi
  done

  if ! $any; then
    warn "No scripts found in scripts/ops"
    inc_warn
  fi
}

check_docker_access() {
  log "Docker access diagnostics"

  if ! command -v docker >/dev/null 2>&1; then
    err "docker command not found"
    inc_fail
    return
  fi
  ok "docker command available"
  inc_pass

  if id -nG "${CURRENT_USER}" | tr ' ' '\n' | grep -qx docker; then
    ok "User '${CURRENT_USER}' is in docker group"
    inc_pass
  else
    warn "User '${CURRENT_USER}' is not in docker group"
    inc_warn
    note "Fix hint: sudo usermod -aG docker ${CURRENT_USER} && newgrp docker"
  fi

  if [ -S /var/run/docker.sock ]; then
    if [ -r /var/run/docker.sock ] && [ -w /var/run/docker.sock ]; then
      ok "docker.sock is readable+writable"
      inc_pass
    else
      warn "docker.sock exists but lacks rw access"
      inc_warn
      note "Fix hint: sudo chgrp docker /var/run/docker.sock && sudo chmod 660 /var/run/docker.sock"
    fi
  else
    warn "docker.sock not present at /var/run/docker.sock"
    inc_warn
  fi

  if docker info >/dev/null 2>&1; then
    ok "Docker daemon reachable"
    inc_pass
  else
    err "Docker daemon not reachable"
    inc_fail
    note "Fix hint: start/restart docker service and verify socket permissions"
  fi
}

print_summary() {
  echo ""
  echo -e "${BOLD}Permissions Doctor Summary${NC}"
  echo "  pass: ${PASS_COUNT}"
  echo "  warnings: ${WARN_COUNT}"
  echo "  failures: ${FAIL_COUNT}"
  echo ""
}

echo ""
echo -e "${BOLD}TRION Permissions Doctor${NC}"
echo "repo: ${REPO_ROOT}"
echo "user: ${CURRENT_USER}:${CURRENT_GROUP}"
echo ""

if ($OPT_FIX_SAFE || $OPT_FIX_DOCKER) && ! $OPT_DRY_RUN && ! $OPT_YES; then
  echo -ne "Type PERM_FIX to continue: "
  read -r confirm
  if [ "${confirm}" != "PERM_FIX" ]; then
    echo "Aborted."
    exit 0
  fi
fi

log "Checking core directories"
for d in "${TARGET_DIRS[@]}"; do
  check_directory "${d}"
done

log "Checking lock paths"
for l in "${LOCK_FILES[@]}"; do
  check_lock_file "${l}"
done

log "Checking ops script executability"
check_ops_scripts

if $OPT_FIX_DOCKER; then
  check_docker_access
else
  note "Docker diagnostics skipped (use --fix-docker)"
fi

print_summary

if [ "${FAIL_COUNT}" -gt 0 ]; then
  exit 1
fi

exit 0
