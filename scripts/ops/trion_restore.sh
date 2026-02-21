#!/usr/bin/env bash
# ============================================================
# scripts/ops/trion_restore.sh — TRION Restore / Clean Install
# ============================================================
# Restores deterministic runtime defaults:
#   1) default blueprints (truth store + optional graph sync)
#   2) TRION home base structure
#   3) core skills registry entries (manifest-driven)
#
# Modes:
#   --soft (default): restore defaults, keep user data where possible
#   --hard: wipe runtime/user data, then restore defaults
#
# Optional flags:
#   --reseed-blueprints  reseed default blueprints (auto-enabled in --hard)
#   --reseed-skills      verify/seed core skills from restore manifest
#   --pull-images        pull blueprint images after reseed
#   --keep-protocol      do not wipe memory/*.md + protocol status files (hard only)
#   --keep-csv           do not wipe memory_speicher/*.csv + digest state/lock (hard only)
#   --skip-graph         skip blueprint graph sync
#   --smoke-test         run post-restore API smoke checks
#   --skip-home-start    do not auto-start TRION home container
#   --plan               print restore plan and exit
#   --dry-run            print actions only
#   --yes / --non-interactive  skip prompt confirmations
#
# Safety:
#   - lockfile (/tmp/trion_restore.lock) prevents parallel runs
#   - path guard: only operates inside detected repo root
#   - typed confirmation required unless --yes/--non-interactive
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
LOCK_FILE_DEFAULT="${REPO_ROOT}/memory_speicher/trion_restore.lock"
LOCK_FILE="${TRION_RESTORE_LOCK_FILE:-${LOCK_FILE_DEFAULT}}"

MEM_CONTAINER="mcp-sql-memory"
MEM_DB="/app/data/memory.db"
CMD_CONTAINER="jarvis-admin-api"
CMD_DB="/app/data/commander.db"
DIGEST_WORKER="digest-worker"
TRION_LABEL="trion.managed=true"

PROTOCOL_DIR="${REPO_ROOT}/memory"
DIGEST_DIR="${REPO_ROOT}/memory_speicher"
LOG_DIR="${REPO_ROOT}/logs"
MANIFEST_PATH="${RESTORE_MANIFEST_PATH:-${REPO_ROOT}/seed/restore_manifest.json}"
SHARED_SKILLS_DIR="${TRION_SHARED_SKILLS_DIR:-/DATA/AppData/MCP/Jarvis/shared_skills}"

path_guard_within_repo() {
    local p
    p="$(realpath "$1" 2>/dev/null || true)"
    [ -n "${p}" ] || return 1
    case "${p}" in
        "${REPO_ROOT}"|${REPO_ROOT}/*) return 0 ;;
        *) return 1 ;;
    esac
}

# hard-wipe target tables
MEM_HARD_TABLES=(memory facts embeddings graph_nodes graph_edges \
                 workspace_entries workspace_events task_active task_archive \
                 skill_metrics secrets)
CMD_HARD_TABLES=(container_log secret_access_log secrets blueprints)

OPT_HARD=false
OPT_RESEED_BLUEPRINTS=false
OPT_RESEED_SKILLS=false
OPT_PULL_IMAGES=false
OPT_KEEP_PROTOCOL=false
OPT_KEEP_CSV=false
OPT_SKIP_GRAPH=false
OPT_SMOKE_TEST=false
OPT_SKIP_HOME_START=false
OPT_PLAN=false
OPT_DRY_RUN=false
OPT_YES=false
OPT_NON_INTERACTIVE=false

for arg in "$@"; do
    case "$arg" in
        --soft) ;;
        --hard) OPT_HARD=true ;;
        --reseed-blueprints) OPT_RESEED_BLUEPRINTS=true ;;
        --reseed-skills) OPT_RESEED_SKILLS=true ;;
        --pull-images) OPT_PULL_IMAGES=true ;;
        --keep-protocol) OPT_KEEP_PROTOCOL=true ;;
        --keep-csv) OPT_KEEP_CSV=true ;;
        --skip-graph) OPT_SKIP_GRAPH=true ;;
        --smoke-test) OPT_SMOKE_TEST=true ;;
        --skip-home-start) OPT_SKIP_HOME_START=true ;;
        --plan) OPT_PLAN=true ;;
        --dry-run) OPT_DRY_RUN=true ;;
        --yes) OPT_YES=true ;;
        --non-interactive) OPT_NON_INTERACTIVE=true ;;
        -h|--help)
            cat <<'EOF'
Usage: scripts/ops/trion_restore.sh [OPTIONS]

Modes:
  --soft                Restore defaults (keep user data where possible) [default]
  --hard                Wipe runtime/user data, then restore defaults

Restore actions:
  --reseed-blueprints   Seed default blueprints
  --reseed-skills       Verify/seed core skills from restore manifest
  --pull-images         Pull blueprint images after reseed
  --keep-protocol       Keep protocol files in memory/*.md (hard only)
  --keep-csv            Keep digest CSV/state/lock files (hard only)
  --skip-graph          Skip blueprint graph sync
  --smoke-test          Run API smoke checks after restore
  --skip-home-start     Do not auto-start TRION home container

Control:
  --plan                Print phase checklist and exit
  --dry-run             Print actions only
  --yes                 Skip interactive confirmation
  --non-interactive     Alias for non-prompt mode (requires --yes)
  -h, --help            Show this help

Examples:
  bash scripts/ops/trion_restore.sh --plan
  bash scripts/ops/trion_restore.sh --soft --reseed-blueprints --reseed-skills
  bash scripts/ops/trion_restore.sh --hard --reseed-skills --smoke-test
  bash scripts/ops/trion_restore.sh --hard --keep-protocol --keep-csv --yes --non-interactive
EOF
            exit 0
            ;;
        *)
            echo "Unknown option: $arg" >&2
            exit 1
            ;;
    esac
done

if $OPT_HARD; then
    OPT_RESEED_BLUEPRINTS=true
fi

if $OPT_NON_INTERACTIVE && ! $OPT_YES; then
    echo "ERROR: --non-interactive requires --yes." >&2
    exit 2
fi

mkdir -p "${LOG_DIR}"
REPORT_TS="$(date +%Y%m%d-%H%M%S)"
REPORT_FILE="${LOG_DIR}/restore_report_${REPORT_TS}.json"

RESTORE_STATUS="success"
ERRORS=""
DOCKER_OK=true
PAUSED_DIGEST=false
WAS_DIGEST_RUNNING=false
WAS_ADMIN_RUNNING=false
WAS_MEM_RUNNING=false

BLUEPRINT_COUNT="0"
GRAPH_SYNC_COUNT="0"
SKILLS_ADDED="0"
SKILLS_VERIFIED="0"
SKILLS_MISSING=""
IMAGES_PULLED="0"
SMOKE_STATUS="skipped"
SMOKE_FAILURES="0"
TRION_HOME_CID=""

log()  { echo -e "${CYAN}[TRION-RESTORE]${NC} $*"; }
ok()   { echo -e "  ${GREEN}OK${NC} $*"; }
warn() { echo -e "  ${YELLOW}WARN${NC} $*"; }
err()  { echo -e "  ${RED}ERR${NC} $*" >&2; }

append_error() {
    local msg="$1"
    ERRORS="${ERRORS}${msg}|"
    RESTORE_STATUS="error"
}

running() { docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$1"; }
exists() { docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$1"; }

count_rows() {
    local ctr="$1" db="$2" tbl="$3"
    docker exec "$ctr" python3 -c "
import sqlite3
try:
    print(sqlite3.connect('$db').execute('SELECT COUNT(*) FROM $tbl').fetchone()[0])
except Exception:
    print(0)
" 2>/dev/null || echo 0
}

do_cmd() {
    if $OPT_DRY_RUN; then
        echo -e "  ${DIM}[dry-run] $*${NC}"
        return 0
    fi
    "$@"
}

py_list() {
    local IFS=','
    echo "'${*}'" | sed "s/,/','/g"
}

manifest_core_skills() {
    if [ ! -f "${MANIFEST_PATH}" ]; then
        return 0
    fi
    python3 - "${MANIFEST_PATH}" <<'PY'
import json,sys
path=sys.argv[1]
try:
    obj=json.load(open(path,"r",encoding="utf-8"))
except Exception:
    sys.exit(0)
for item in obj.get("core_skills",[]):
    if isinstance(item,dict):
        name=item.get("name","").strip()
    else:
        name=str(item).strip()
    if name:
        print(name)
PY
}

manifest_list_values() {
    local key="$1"
    shift || true
    if [ -f "${MANIFEST_PATH}" ]; then
        local out
        out="$(python3 - "${MANIFEST_PATH}" "${key}" <<'PY'
import json,sys
path=sys.argv[1]
key=sys.argv[2]
try:
    obj=json.load(open(path,"r",encoding="utf-8"))
except Exception:
    sys.exit(0)
vals=obj.get(key,[])
if isinstance(vals,list):
    for v in vals:
        if isinstance(v,str) and v.strip():
            print(v.strip())
PY
)"
        if [ -n "${out}" ]; then
            printf "%s\n" "${out}"
            return 0
        fi
    fi
    for item in "$@"; do
        printf "%s\n" "${item}"
    done
}

print_plan() {
    local mode="soft"
    $OPT_HARD && mode="hard"
    echo "TRION Restore Plan"
    echo "  mode: ${mode}"
    echo "  manifest: ${MANIFEST_PATH}"
    echo "  phases:"
    echo "    A) Preflight + lock + safety gates"
    echo "    B) Pause writers (digest/admin ingress), ensure core services"
    echo "    C) Restore base dirs + TRION home skeleton"
    echo "    D) Blueprint restore (seed + optional graph sync)"
    if $OPT_RESEED_SKILLS; then
        echo "    E) Skill restore (core skills from manifest)"
    else
        echo "    E) Skill restore skipped (use --reseed-skills)"
    fi
    if $OPT_SKIP_HOME_START; then
        echo "    F) TRION home container start skipped (--skip-home-start)"
    else
        echo "    F) Ensure TRION home container"
    fi
    if $OPT_PULL_IMAGES; then
        echo "    G) Pull blueprint images"
    else
        echo "    G) Image pull skipped (use --pull-images)"
    fi
    if $OPT_SMOKE_TEST; then
        echo "    H) Smoke tests (/health,/api/tags,/api/commander/blueprints,/api/workspace-events)"
    else
        echo "    H) Smoke tests skipped (use --smoke-test)"
    fi
    echo "    I) Restore report: ${REPORT_FILE}"
}

write_report() {
    export REPORT_FILE RESTORE_STATUS ERRORS
    export OPT_HARD OPT_RESEED_BLUEPRINTS OPT_RESEED_SKILLS OPT_PULL_IMAGES
    export OPT_KEEP_PROTOCOL OPT_KEEP_CSV OPT_SKIP_GRAPH OPT_SMOKE_TEST OPT_DRY_RUN OPT_SKIP_HOME_START
    export BLUEPRINT_COUNT GRAPH_SYNC_COUNT SKILLS_ADDED SKILLS_VERIFIED SKILLS_MISSING
    export IMAGES_PULLED SMOKE_STATUS SMOKE_FAILURES MANIFEST_PATH TRION_HOME_CID

    python3 - <<'PY' || true
import json,os,datetime
path=os.environ["REPORT_FILE"]
def b(name): return os.environ.get(name,"false").lower()=="true"
data={
  "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
  "status": os.environ.get("RESTORE_STATUS","unknown"),
  "manifest": os.environ.get("MANIFEST_PATH",""),
  "options": {
    "hard": b("OPT_HARD"),
    "reseed_blueprints": b("OPT_RESEED_BLUEPRINTS"),
    "reseed_skills": b("OPT_RESEED_SKILLS"),
    "pull_images": b("OPT_PULL_IMAGES"),
    "keep_protocol": b("OPT_KEEP_PROTOCOL"),
    "keep_csv": b("OPT_KEEP_CSV"),
    "skip_graph": b("OPT_SKIP_GRAPH"),
    "smoke_test": b("OPT_SMOKE_TEST"),
    "skip_home_start": b("OPT_SKIP_HOME_START"),
    "dry_run": b("OPT_DRY_RUN"),
  },
  "results": {
    "blueprints_seeded_count": int(os.environ.get("BLUEPRINT_COUNT","0") or 0),
    "graph_sync_count": int(os.environ.get("GRAPH_SYNC_COUNT","0") or 0),
    "skills_added": int(os.environ.get("SKILLS_ADDED","0") or 0),
    "skills_verified": int(os.environ.get("SKILLS_VERIFIED","0") or 0),
    "skills_missing": [x for x in os.environ.get("SKILLS_MISSING","").split(",") if x],
    "images_pulled": int(os.environ.get("IMAGES_PULLED","0") or 0),
    "trion_home_container_id": os.environ.get("TRION_HOME_CID",""),
    "smoke_status": os.environ.get("SMOKE_STATUS","skipped"),
    "smoke_failures": int(os.environ.get("SMOKE_FAILURES","0") or 0),
  },
  "errors": [x for x in os.environ.get("ERRORS","").split("|") if x],
}
with open(path,"w",encoding="utf-8") as f:
    json.dump(data,f,indent=2)
print(path)
PY
}

if $OPT_PLAN; then
    print_plan
    exit 0
fi

cleanup() {
    local ec=$?
    if [ $ec -ne 0 ]; then
        RESTORE_STATUS="error"
    fi

    if ! $OPT_DRY_RUN && $PAUSED_DIGEST; then
        if docker compose -f "${COMPOSE_FILE}" start "${DIGEST_WORKER}" >/dev/null 2>&1; then
            :
        else
            append_error "failed_to_resume_digest_worker"
        fi
    fi

    write_report >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

if [ ! -f "${COMPOSE_FILE}" ]; then
    err "docker-compose.yml not found: ${COMPOSE_FILE}"
    exit 2
fi

# lock
mkdir -p "$(dirname "${LOCK_FILE}")"
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
    err "Another restore/reset process is already running (lock: ${LOCK_FILE})."
    exit 3
fi

if ! docker info >/dev/null 2>&1; then
    DOCKER_OK=false
fi

if ! $DOCKER_OK && ! $OPT_DRY_RUN; then
    err "Docker daemon not reachable (permission/socket)."
    exit 2
fi

if ! $DOCKER_OK && $OPT_DRY_RUN; then
    warn "Docker not reachable; dry-run will print plan with unknown runtime counters."
fi

echo ""
echo -e "${BOLD}TRION Restore${NC}"
echo "repo: ${REPO_ROOT}"
echo "report: ${REPORT_FILE}"
echo ""

if [ ! -f "${MANIFEST_PATH}" ]; then
    warn "Manifest not found: ${MANIFEST_PATH} (fallback defaults will be used)."
fi

if $DOCKER_OK; then
    $OPT_DRY_RUN || true
    if running "${DIGEST_WORKER}"; then WAS_DIGEST_RUNNING=true; fi
    if running "${CMD_CONTAINER}"; then WAS_ADMIN_RUNNING=true; fi
    if running "${MEM_CONTAINER}"; then WAS_MEM_RUNNING=true; fi
fi

if ! $OPT_DRY_RUN && ! $OPT_YES; then
    if $OPT_HARD; then
        echo -ne "Type HARD_RESTORE to continue: "
        read -r c
        [ "${c}" = "HARD_RESTORE" ] || { echo "Aborted."; exit 0; }
    else
        echo -ne "Type RESTORE to continue: "
        read -r c
        [ "${c}" = "RESTORE" ] || { echo "Aborted."; exit 0; }
    fi
fi

log "Phase A: Preflight"
for _p in "${REPO_ROOT}" "${PROTOCOL_DIR}" "${DIGEST_DIR}" "${LOG_DIR}"; do
    if ! path_guard_within_repo "${_p}"; then
        err "Path guard rejected: ${_p}"
        exit 2
    fi
done
HOST_DIRS=()
while IFS= read -r d; do
    [ -n "${d}" ] && HOST_DIRS+=("${REPO_ROOT}/${d}")
done < <(manifest_list_values "core_dirs" "memory" "memory_speicher" "logs" "scripts/ops")
for d in "${HOST_DIRS[@]}"; do
    mkdir -p "${d}"
done
mkdir -p "${REPO_ROOT}/seed"
ok "Base directories present"

if ! $OPT_KEEP_PROTOCOL; then
    : # explicit no-op marker for plan/readability
fi

log "Phase B: Service control"
if $DOCKER_OK; then
    if running "${DIGEST_WORKER}"; then
        do_cmd docker compose -f "${COMPOSE_FILE}" stop "${DIGEST_WORKER}"
        PAUSED_DIGEST=true
        ok "Paused digest-worker"
    else
        warn "digest-worker not running"
    fi

    # stop ingress to reduce concurrent writes during restore
    if running "${CMD_CONTAINER}"; then
        do_cmd docker compose -f "${COMPOSE_FILE}" stop "${CMD_CONTAINER}"
        ok "Stopped admin ingress"
    else
        warn "jarvis-admin-api not running"
    fi

    # core services for restore phases
    do_cmd docker compose -f "${COMPOSE_FILE}" start "${MEM_CONTAINER}" "${CMD_CONTAINER}"
    ok "Core services started"
fi

log "Phase C: TRION home + defaults"
TRION_HOME_DIRS=()
while IFS= read -r d; do
    [ -n "${d}" ] && TRION_HOME_DIRS+=("${d}")
done < <(manifest_list_values "trion_home_dirs" "workspace" "state" "logs")
THD_JOINED="${TRION_HOME_DIRS[*]}"
if ! $OPT_DRY_RUN; then
    docker exec -e THD_JOINED="${THD_JOINED}" "${CMD_CONTAINER}" sh -lc '
set -e
if [ "'"${OPT_HARD}"'" = "true" ]; then
  rm -rf /trion-home/* /trion-home/.[!.]* 2>/dev/null || true
fi
for d in ${THD_JOINED}; do
  mkdir -p "/trion-home/${d}"
done
if [ ! -f /trion-home/README_RESTORED.md ]; then
  cat > /trion-home/README_RESTORED.md <<TXT
TRION Home restored by scripts/ops/trion_restore.sh
TXT
fi
'
    ok "TRION home prepared"
else
    echo "  [dry-run] prepare /trion-home/{${THD_JOINED}}"
fi

# hard mode runtime wipe (optional keeps)
if $OPT_HARD; then
    log "Phase C.1: Hard mode runtime wipe"
    if $OPT_DRY_RUN; then
        echo "  [dry-run] wipe memory tables: ${MEM_HARD_TABLES[*]}"
        echo "  [dry-run] wipe commander tables: ${CMD_HARD_TABLES[*]}"
    else
        PY_MEM_TABLES="$(py_list "${MEM_HARD_TABLES[@]}")"
        docker exec -i "${MEM_CONTAINER}" python3 - <<PY
import sqlite3
conn=sqlite3.connect("${MEM_DB}")
conn.execute("PRAGMA busy_timeout=5000")
conn.execute("BEGIN IMMEDIATE")
for t in [${PY_MEM_TABLES}]:
    try:
        conn.execute(f"DELETE FROM {t}")
        print(f"cleared {t}")
    except Exception as e:
        print(f"skip {t}: {e}")
for fts in ("memory_fts","memory_fts_data","memory_fts_idx","memory_fts_docsize","memory_fts_config","memory_fts_content"):
    try: conn.execute(f"DELETE FROM {fts}")
    except Exception: pass
try: conn.execute("DELETE FROM sqlite_sequence")
except Exception: pass
conn.commit()
conn.close()
PY

        PY_CMD_TABLES="$(py_list "${CMD_HARD_TABLES[@]}")"
        docker exec -i "${CMD_CONTAINER}" python3 - <<PY
import sqlite3
conn=sqlite3.connect("${CMD_DB}")
conn.execute("PRAGMA busy_timeout=5000")
conn.execute("BEGIN IMMEDIATE")
for t in [${PY_CMD_TABLES}]:
    try:
        conn.execute(f"DELETE FROM {t}")
        print(f"cleared {t}")
    except Exception as e:
        print(f"skip {t}: {e}")
try: conn.execute("DELETE FROM sqlite_sequence")
except Exception: pass
conn.commit()
conn.close()
PY
        ok "Hard DB wipe completed"
    fi

    # managed containers/volumes/network cleanup
    if $OPT_DRY_RUN; then
        echo "  [dry-run] remove managed containers/volumes/network label=${TRION_LABEL}"
    else
        CIDS="$(docker ps -aq --filter "label=${TRION_LABEL}" 2>/dev/null || true)"
        if [ -n "${CIDS}" ]; then
            # shellcheck disable=SC2086
            docker rm -f ${CIDS} >/dev/null 2>&1 || true
        fi
        VOLS="$(docker volume ls -q --filter "label=${TRION_LABEL}" 2>/dev/null || true)"
        if [ -n "${VOLS}" ]; then
            # shellcheck disable=SC2086
            docker volume rm ${VOLS} >/dev/null 2>&1 || true
        fi
        docker network rm trion-sandbox >/dev/null 2>&1 || true
        ok "Managed runtime resources cleanup done"
    fi

    if ! $OPT_KEEP_CSV; then
        if $OPT_DRY_RUN; then
            echo "  [dry-run] remove ${DIGEST_DIR}/*.csv + digest_state/lock"
        else
            shopt -s nullglob
            _csvs=("${DIGEST_DIR}"/*.csv)
            [ ${#_csvs[@]} -gt 0 ] && rm -f "${_csvs[@]}"
            shopt -u nullglob
            rm -f "${DIGEST_DIR}/digest_state.json" \
                  "${DIGEST_DIR}/digest.lock" \
                  "${DIGEST_DIR}/digest.lock.takeover" \
                  "${DIGEST_DIR}/digest.lock.tmp" 2>/dev/null || true
            ok "Digest files cleaned"
        fi
    else
        warn "keep-csv enabled; digest files preserved"
    fi

    if ! $OPT_KEEP_PROTOCOL; then
        if $OPT_DRY_RUN; then
            echo "  [dry-run] remove ${PROTOCOL_DIR}/*.md + protocol status files"
        else
            shopt -s nullglob
            _mds=("${PROTOCOL_DIR}"/*.md)
            [ ${#_mds[@]} -gt 0 ] && rm -f "${_mds[@]}"
            shopt -u nullglob
            rm -f "${PROTOCOL_DIR}/.protocol_status.json" \
                  "${PROTOCOL_DIR}/.daily_summary_status.json" 2>/dev/null || true
            ok "Protocol files cleaned"
        fi
    else
        warn "keep-protocol enabled; protocol files preserved"
    fi
fi

# ensure baseline status files
if $OPT_DRY_RUN; then
    echo "  [dry-run] ensure protocol status files in ${PROTOCOL_DIR}"
else
    [ -f "${PROTOCOL_DIR}/.protocol_status.json" ] || printf "{}\n" > "${PROTOCOL_DIR}/.protocol_status.json"
    [ -f "${PROTOCOL_DIR}/.daily_summary_status.json" ] || printf "{}\n" > "${PROTOCOL_DIR}/.daily_summary_status.json"
    ok "Protocol status defaults ensured"
fi

log "Phase D: Blueprints"
if $OPT_RESEED_BLUEPRINTS; then
    if $OPT_DRY_RUN; then
        echo "  [dry-run] seed_default_blueprints()"
    else
        if ! BP_OUT="$(docker exec -i "${CMD_CONTAINER}" python3 - <<'PY' 2>&1
import os
import sqlite3
from container_commander.blueprint_store import init_db, seed_default_blueprints, list_blueprints

db_path = os.environ.get("COMMANDER_DB_PATH", "/app/data/commander.db")

def _counts():
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM blueprints")
        total = int(cur.fetchone()[0])
        try:
            cur.execute("SELECT COUNT(*) FROM blueprints WHERE is_deleted=1")
            deleted = int(cur.fetchone()[0])
        except Exception:
            deleted = 0
        return total, deleted
    finally:
        conn.close()

init_db()
pre_total, pre_deleted = _counts()
seed_default_blueprints()
count = len(list_blueprints())
retry_soft_deleted_purge = False

if count == 0:
    post_total, post_deleted = _counts()
    if post_total > 0 and post_deleted == post_total:
        retry_soft_deleted_purge = True
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("DELETE FROM blueprints WHERE is_deleted=1")
            conn.commit()
        finally:
            conn.close()
        seed_default_blueprints()
        count = len(list_blueprints())
    else:
        retry_soft_deleted_purge = False
else:
    post_total, post_deleted = _counts()

post_total, post_deleted = _counts()
print("BP_METRIC_count=" + str(count))
print("BP_METRIC_pre_total=" + str(pre_total))
print("BP_METRIC_pre_deleted=" + str(pre_deleted))
print("BP_METRIC_post_total=" + str(post_total))
print("BP_METRIC_post_deleted=" + str(post_deleted))
print("BP_METRIC_retry_soft_deleted_purge=" + ("1" if retry_soft_deleted_purge else "0"))
PY
)";
        then
            BLUEPRINT_COUNT="0"
            append_error "blueprint_seed_exec_failed"
            warn "Blueprint seed command failed: ${BP_OUT:-no_output}"
        else
        BLUEPRINT_COUNT="$(echo "${BP_OUT}" | awk -F= '/^BP_METRIC_count=/{print $2}' | tail -n1)"
        BP_PRE_TOTAL="$(echo "${BP_OUT}" | awk -F= '/^BP_METRIC_pre_total=/{print $2}' | tail -n1)"
        BP_PRE_DELETED="$(echo "${BP_OUT}" | awk -F= '/^BP_METRIC_pre_deleted=/{print $2}' | tail -n1)"
        BP_POST_TOTAL="$(echo "${BP_OUT}" | awk -F= '/^BP_METRIC_post_total=/{print $2}' | tail -n1)"
        BP_POST_DELETED="$(echo "${BP_OUT}" | awk -F= '/^BP_METRIC_post_deleted=/{print $2}' | tail -n1)"
        BP_RETRY_PURGE="$(echo "${BP_OUT}" | awk -F= '/^BP_METRIC_retry_soft_deleted_purge=/{print $2}' | tail -n1)"
        if [ -z "${BLUEPRINT_COUNT}" ]; then
            append_error "blueprint_seed_parse_failed"
            warn "Blueprint seed metrics missing. Raw output: $(echo "${BP_OUT}" | tr '\n' ' ' | cut -c1-400)"
            BLUEPRINT_COUNT="0"
        fi
        BLUEPRINT_COUNT="${BLUEPRINT_COUNT:-0}"
        if [ "${BLUEPRINT_COUNT}" -eq 0 ]; then
            append_error "blueprint_seed_empty"
            warn "Blueprint seed returned count=0 (expected >0, pre_total=${BP_PRE_TOTAL:-?}, pre_deleted=${BP_PRE_DELETED:-?}, post_total=${BP_POST_TOTAL:-?}, post_deleted=${BP_POST_DELETED:-?}, retry_purge=${BP_RETRY_PURGE:-0})"
        else
            ok "Blueprints seeded/verifed (count=${BLUEPRINT_COUNT})"
            if [ "${BP_RETRY_PURGE:-0}" = "1" ]; then
                warn "Recovered from soft-deleted default blueprints via purge+reseed"
            fi
        fi
        fi
    fi

    if ! $OPT_SKIP_GRAPH; then
        if $OPT_DRY_RUN; then
            echo "  [dry-run] sync_blueprints_to_graph()"
        else
            GS_OUT="$(docker exec -i "${CMD_CONTAINER}" python3 - <<'PY'
from container_commander.blueprint_store import sync_blueprints_to_graph
print(sync_blueprints_to_graph())
PY
)"
            GRAPH_SYNC_COUNT="$(echo "${GS_OUT}" | tail -n1 | tr -dc '0-9')"
            GRAPH_SYNC_COUNT="${GRAPH_SYNC_COUNT:-0}"
            ok "Blueprint graph sync complete (updated=${GRAPH_SYNC_COUNT})"
        fi
    else
        warn "skip-graph enabled; graph sync skipped"
    fi
else
    warn "reseed-blueprints disabled; skipping blueprint seed"
fi

log "Phase E: Skills"
if $OPT_RESEED_SKILLS; then
    if $OPT_DRY_RUN; then
        echo "  [dry-run] verify/seed skills in ${SHARED_SKILLS_DIR}/_registry/installed.json"
    else
        SK_OUT="$(python3 - "${MANIFEST_PATH}" "${SHARED_SKILLS_DIR}" <<'PY'
import json,sys,os,datetime
manifest_path=sys.argv[1]
skills_dir=sys.argv[2]
registry_dir=os.path.join(skills_dir,"_registry")
registry_path=os.path.join(registry_dir,"installed.json")
os.makedirs(registry_dir,exist_ok=True)
core=[]
if os.path.exists(manifest_path):
    try:
        obj=json.load(open(manifest_path,"r",encoding="utf-8"))
        core=obj.get("core_skills",[])
    except Exception:
        core=[]
norm=[]
for item in core:
    if isinstance(item,dict):
        name=str(item.get("name","")).strip()
        version=str(item.get("version","1.0.0")).strip() or "1.0.0"
        description=str(item.get("description","")).strip()
    else:
        name=str(item).strip()
        version="1.0.0"
        description=""
    if name:
        norm.append((name,version,description))
installed={}
if os.path.exists(registry_path):
    try:
        installed=json.load(open(registry_path,"r",encoding="utf-8"))
        if not isinstance(installed,dict):
            installed={}
    except Exception:
        installed={}
added=0
verified=0
missing=[]
now=datetime.datetime.now(datetime.timezone.utc).isoformat()
for name,version,description in norm:
    skill_dir=os.path.join(skills_dir,name)
    if not os.path.isdir(skill_dir):
        missing.append(name)
        continue
    prev=installed.get(name)
    if isinstance(prev,dict) and str(prev.get("version",""))==version:
        verified+=1
        continue
    installed[name]={
        "version": version,
        "installed_at": now,
        "description": description,
        "triggers": prev.get("triggers",[]) if isinstance(prev,dict) else []
    }
    added+=1
tmp=registry_path+".tmp"
with open(tmp,"w",encoding="utf-8") as f:
    json.dump(installed,f,indent=2,ensure_ascii=False)
os.replace(tmp,registry_path)
print(f"added={added}")
print(f"verified={verified}")
print("missing="+",".join(missing))
PY
)"
        SKILLS_ADDED="$(echo "${SK_OUT}" | awk -F= '/^added=/{print $2}' | tail -n1)"
        SKILLS_VERIFIED="$(echo "${SK_OUT}" | awk -F= '/^verified=/{print $2}' | tail -n1)"
        SKILLS_MISSING="$(echo "${SK_OUT}" | awk -F= '/^missing=/{print $2}' | tail -n1)"
        SKILLS_ADDED="${SKILLS_ADDED:-0}"
        SKILLS_VERIFIED="${SKILLS_VERIFIED:-0}"
        ok "Skills reseeded (added=${SKILLS_ADDED}, verified=${SKILLS_VERIFIED})"
        [ -n "${SKILLS_MISSING}" ] && warn "Missing core skill dirs: ${SKILLS_MISSING}"
    fi
else
    warn "reseed-skills disabled; skipping skills phase"
fi

log "Phase F: Ensure TRION home container"
if $OPT_SKIP_HOME_START; then
    warn "skip-home-start enabled; TRION home container not auto-started"
else
    if $OPT_DRY_RUN; then
        echo "  [dry-run] ensure TRION home container via container_commander.mcp_tools._ensure_trion_home()"
    else
        if ! HOME_OUT="$(docker exec -i "${CMD_CONTAINER}" python3 - <<'PY' 2>&1
from container_commander.mcp_tools import _ensure_trion_home
cid = _ensure_trion_home()
print("HOME_METRIC_cid=" + str(cid))
PY
)"; then
            append_error "trion_home_ensure_failed"
            warn "TRION home ensure failed: ${HOME_OUT:-no_output}"
        else
            TRION_HOME_CID="$(echo "${HOME_OUT}" | awk -F= '/^HOME_METRIC_cid=/{print $2}' | tail -n1)"
            if [ -z "${TRION_HOME_CID}" ]; then
                TRION_HOME_CID="$(docker exec -i "${CMD_CONTAINER}" python3 - <<'PY' 2>/dev/null || true
from container_commander.engine import list_containers
for c in list_containers():
    if getattr(c, "blueprint_id", "") == "trion-home" and getattr(c, "status", None) and getattr(c.status, "value", "") == "running":
        print(getattr(c, "container_id", ""))
        break
PY
)"
            fi
            if [ -n "${TRION_HOME_CID}" ]; then
                ok "TRION home container ensured (${TRION_HOME_CID:0:12})"
            else
                append_error "trion_home_missing"
                warn "TRION home ensure returned no container id. Raw output: $(echo "${HOME_OUT}" | tr '\n' ' ' | cut -c1-400)"
            fi
        fi
    fi
fi

log "Phase G: Image pull"
if $OPT_PULL_IMAGES; then
    if $OPT_DRY_RUN; then
        echo "  [dry-run] pull blueprint images from blueprint store"
    else
        IMG_LIST="$(docker exec -i "${CMD_CONTAINER}" python3 - <<'PY'
import sqlite3
db="/app/data/commander.db"
conn=sqlite3.connect(db)
rows=conn.execute("SELECT DISTINCT image FROM blueprints WHERE image IS NOT NULL AND TRIM(image) != ''").fetchall()
conn.close()
for r in rows:
    print(r[0])
PY
)"
        while IFS= read -r image; do
            [ -z "${image}" ] && continue
            if docker pull "${image}" >/dev/null 2>&1; then
                IMAGES_PULLED=$((IMAGES_PULLED + 1))
                ok "Pulled image: ${image}"
            else
                warn "Failed to pull image: ${image}"
            fi
        done <<< "${IMG_LIST}"
        ok "Image pull phase done (pulled=${IMAGES_PULLED})"
    fi
else
    warn "pull-images disabled; skipping image pull"
fi

log "Phase H: Service finalize"
if $DOCKER_OK; then
    do_cmd docker compose -f "${COMPOSE_FILE}" start "${MEM_CONTAINER}" "${CMD_CONTAINER}"
    ok "Core services running"
fi

if $OPT_SMOKE_TEST; then
    log "Phase I: Smoke tests"
    if $OPT_DRY_RUN; then
        echo "  [dry-run] smoke: /health, /api/tags, /api/commander/blueprints, /api/workspace-events"
        SMOKE_STATUS="skipped_dry_run"
    else
        SMOKE_STATUS="ok"
        _check() {
            local url="$1"
            local code
            code="$(curl -s -o /tmp/trion_restore_smoke.out -w '%{http_code}' --max-time 10 "${url}" || true)"
            if [ "${code}" != "200" ]; then
                SMOKE_FAILURES=$((SMOKE_FAILURES + 1))
                SMOKE_STATUS="failed"
                append_error "smoke_failed:${url}:${code}"
                warn "Smoke fail ${url} (code=${code})"
            else
                ok "Smoke ok ${url}"
            fi
        }
        _check "http://localhost:8200/health"
        _check "http://localhost:8200/api/tags"
        _check "http://localhost:8200/api/commander/blueprints"
        _check "http://localhost:8200/api/workspace-events?limit=1"
    fi
fi

echo ""
ok "Restore finished (status=${RESTORE_STATUS})"
echo "Report: ${REPORT_FILE}"
echo ""

if [ "${SMOKE_STATUS}" = "failed" ]; then
    exit 4
fi
