#!/usr/bin/env bash
# ============================================================
# scripts/ops/trion_live_reset.sh — TRION Live Reset (for tests)
# ============================================================
# Goal: Reset runtime/test data while stack stays online.
#
# Modes (combinable):
#   (default/--soft)  : clear runtime memory/graph/workspace/digest + managed
#                       containers/volumes/network (label-based)
#   --hard            : additionally wipe blueprints + /trion-home
#   --reseed-blueprints : with --hard, reseed default blueprints
#   --github-ready    : additionally remove local cache/temp artefacts
#   --dry-run         : print actions only
#   --keep-digest-worker : do not pause digest-worker during reset
#   --keep-protocol   : keep protocol markdown/status files (memory/*.md)
#
# Safety:
#   - set -euo pipefail
#   - typed confirmation in non-dry-run mode
#   - label-based cleanup: trion.managed=true
# ============================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

COMPOSE_DIR="/DATA/AppData/MCP/Jarvis/Jarvis"
COMPOSE_FILE="${COMPOSE_DIR}/docker-compose.yml"
TRION_LABEL="trion.managed=true"

MEM_CONTAINER="mcp-sql-memory"
MEM_DB="/app/data/memory.db"
CMD_CONTAINER="jarvis-admin-api"
CMD_DB="/app/data/commander.db"
DIGEST_WORKER="digest-worker"
DIGEST_DIR="${COMPOSE_DIR}/memory_speicher"
PROTOCOL_DIR="${COMPOSE_DIR}/memory"

MEM_SOFT_TABLES=(memory facts embeddings graph_nodes graph_edges \
                 workspace_entries workspace_events \
                 task_active task_archive skill_metrics secrets)
CMD_SOFT_TABLES=(container_log secret_access_log)
CMD_HARD_TABLES=(blueprints)

OPT_HARD=false
OPT_RESEED=false
OPT_GITHUB=false
OPT_DRY=false
OPT_KEEP_DIGEST_WORKER=false
OPT_KEEP_PROTOCOL=false

for arg in "$@"; do
    case "$arg" in
        --soft) ;;  # default
        --hard) OPT_HARD=true ;;
        --reseed-blueprints) OPT_RESEED=true ;;
        --github-ready) OPT_GITHUB=true ;;
        --dry-run) OPT_DRY=true ;;
        --keep-digest-worker) OPT_KEEP_DIGEST_WORKER=true ;;
        --keep-protocol) OPT_KEEP_PROTOCOL=true ;;
        -h|--help)
            cat <<USAGE
Usage: $0 [OPTIONS]

Options:
  --soft                Live reset (default)
  --hard                + wipe blueprints + /trion-home
  --reseed-blueprints   With --hard: reseed default blueprints
  --github-ready        + remove __pycache__, .pytest_cache, *.pyc, *.bak, *.backup-*
  --dry-run             Preview only
  --keep-digest-worker  Do not pause digest-worker during reset
  --keep-protocol       Keep protocol files under memory/*.md
  -h, --help            Show this help

Examples:
  $0
  $0 --dry-run
  $0 --hard --reseed-blueprints
  $0 --soft --github-ready
  $0 --soft --keep-protocol
USAGE
            exit 0 ;;
        *)
            echo "Unknown option: $arg" >&2
            exit 1 ;;
    esac
done

if ! $OPT_HARD && $OPT_RESEED; then
    echo "ERROR: --reseed-blueprints requires --hard" >&2
    exit 1
fi

log()  { echo -e "${CYAN}[TRION-LIVE-RESET]${NC} $*"; }
ok()   { echo -e "  ${GREEN}✓${NC} $*"; }
skip() { echo -e "  ${DIM}→ $*${NC}"; }
note() { echo -e "  ${YELLOW}⚠${NC} $*"; }

exe() {
    if $OPT_DRY; then
        echo -e "  ${DIM}[dry-run] $*${NC}"
        return 0
    fi
    "$@"
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

count_sandbox_ctrs() {
    (docker ps -aq --filter "label=${TRION_LABEL}" 2>/dev/null || true) | wc -l | tr -d ' '
}

count_sandbox_vols() {
    (docker volume ls -q --filter "label=${TRION_LABEL}" 2>/dev/null || true) | wc -l | tr -d ' '
}

py_list() {
    local IFS=','
    echo "'${*}'" | sed "s/,/','/g"
}

DOCKER_OK=true
if ! docker info >/dev/null 2>&1; then
    DOCKER_OK=false
fi

if ! $DOCKER_OK && ! $OPT_DRY; then
    echo "ERROR: Docker daemon not reachable (permission/socket)." >&2
    exit 2
fi

if ! $DOCKER_OK && $OPT_DRY; then
    note "Docker daemon not reachable; dry-run will still print plan with unknown runtime counts."
fi

echo ""
echo -e "${RED}${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${RED}${BOLD}║              TRION  LIVE  RESET                         ║${NC}"
$OPT_DRY && echo -e "${YELLOW}${BOLD}║                    ─── DRY-RUN ───                      ║${NC}"
echo -e "${RED}${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

log "Collecting current live state..."

PRE_SANDBOX_CTRS="?"
PRE_SANDBOX_VOLS="?"
PRE_MEM="?"
PRE_FACTS="?"
PRE_WS="?"
PRE_BP="?"
PRE_CLOG="?"

if $DOCKER_OK; then
    PRE_SANDBOX_CTRS=$(count_sandbox_ctrs)
    PRE_SANDBOX_VOLS=$(count_sandbox_vols)

    if running "$MEM_CONTAINER"; then
        PRE_MEM=$(count_rows "$MEM_CONTAINER" "$MEM_DB" memory)
        PRE_FACTS=$(count_rows "$MEM_CONTAINER" "$MEM_DB" facts)
        PRE_WS=$(count_rows "$MEM_CONTAINER" "$MEM_DB" workspace_entries)
    fi

    if running "$CMD_CONTAINER"; then
        PRE_BP=$(count_rows "$CMD_CONTAINER" "$CMD_DB" blueprints)
        PRE_CLOG=$(count_rows "$CMD_CONTAINER" "$CMD_DB" container_log)
    fi
fi

shopt -s nullglob
_pre_csvs=("${DIGEST_DIR}"/*.csv)
PRE_CSVS=${#_pre_csvs[@]}
shopt -u nullglob
PRE_STATE=$([ -f "${DIGEST_DIR}/digest_state.json" ] && echo "exists" || echo "absent")

MODE="--soft"
$OPT_HARD && MODE="--hard"
$OPT_RESEED && MODE+=" --reseed-blueprints"
$OPT_GITHUB && MODE+=" --github-ready"
$OPT_KEEP_DIGEST_WORKER && MODE+=" --keep-digest-worker"
$OPT_KEEP_PROTOCOL && MODE+=" --keep-protocol"
$OPT_DRY && MODE+=" [DRY-RUN]"

echo -e "${BOLD}Mode:${NC} ${MODE}"
echo ""
echo -e "${BOLD}Will reset during live operation:${NC}"
echo -e "  ${RED}•${NC} Memory tables (memory=${PRE_MEM}, facts=${PRE_FACTS}, workspace_entries=${PRE_WS}, +8 more)"
echo -e "  ${RED}•${NC} Commander logs (container_log=${PRE_CLOG})"
echo -e "  ${RED}•${NC} Digest artifacts (${PRE_CSVS} CSV(s), digest_state=${PRE_STATE}, lock files)"
echo -e "  ${RED}•${NC} Managed runtime containers (${PRE_SANDBOX_CTRS}) + volumes (${PRE_SANDBOX_VOLS}) [label=${TRION_LABEL}]"
if ! $OPT_KEEP_DIGEST_WORKER; then
    echo -e "  ${RED}•${NC} digest-worker will be paused briefly"
fi
if ! $OPT_KEEP_PROTOCOL; then
    echo -e "  ${RED}•${NC} Protocol files/status under memory/ (*.md, .protocol_status.json, .daily_summary_status.json)"
fi
if $OPT_HARD; then
    echo -e "  ${RED}•${NC} Blueprints (${PRE_BP} rows) [--hard]"
    echo -e "  ${RED}•${NC} /trion-home/* [--hard]"
fi
if $OPT_GITHUB; then
    echo -e "  ${RED}•${NC} __pycache__, .pytest_cache, *.pyc, *.bak, *.backup-* [--github-ready]"
fi
echo ""
if $OPT_KEEP_PROTOCOL; then
    echo -e "${BOLD}Preserved:${NC} code/configs, compose files, protocol markdown under memory/*.md"
else
    echo -e "${BOLD}Preserved:${NC} code/configs, compose files"
fi
echo ""

if ! $OPT_DRY; then
    if $OPT_HARD; then
        echo -e "${RED}${BOLD}⚠ LIVE HARD RESET will wipe blueprints and home data.${NC}"
        echo -ne "Type ${BOLD}LIVE_HARD_RESET${NC} to continue: "
        read -r confirm
        [ "$confirm" = "LIVE_HARD_RESET" ] || { echo "Aborted."; exit 0; }
    else
        echo -ne "Type ${BOLD}LIVE_RESET${NC} to continue: "
        read -r confirm
        [ "$confirm" = "LIVE_RESET" ] || { echo "Aborted."; exit 0; }
    fi
fi

PAUSED_DIGEST=false
if ! $OPT_KEEP_DIGEST_WORKER; then
    log "Pausing digest-worker (if running)..."
    if $DOCKER_OK && running "$DIGEST_WORKER"; then
        exe docker compose -f "$COMPOSE_FILE" stop "$DIGEST_WORKER"
        PAUSED_DIGEST=true
        ok "digest-worker paused"
    else
        skip "digest-worker not running"
    fi
    echo ""
fi

log "Removing managed runtime containers (label=${TRION_LABEL})..."
if $OPT_DRY; then
    skip "[dry-run] Would remove containers with label=${TRION_LABEL}"
else
    SANDBOX_IDS=$(docker ps -aq --filter "label=${TRION_LABEL}" 2>/dev/null || true)
    if [ -n "$SANDBOX_IDS" ]; then
        # shellcheck disable=SC2086
        docker rm -f $SANDBOX_IDS
        ok "Managed runtime containers removed"
    else
        skip "No managed containers found"
    fi
fi

log "Removing managed runtime volumes (label=${TRION_LABEL})..."
if $OPT_DRY; then
    skip "[dry-run] Would remove volumes with label=${TRION_LABEL}"
else
    SANDBOX_VOLS=$(docker volume ls -q --filter "label=${TRION_LABEL}" 2>/dev/null || true)
    if [ -n "$SANDBOX_VOLS" ]; then
        # shellcheck disable=SC2086
        docker volume rm $SANDBOX_VOLS || true
        ok "Managed runtime volumes removed"
    else
        skip "No managed volumes found"
    fi
fi

log "Removing trion-sandbox network (if free)..."
if $OPT_DRY; then
    skip "[dry-run] Would remove network trion-sandbox"
else
    if docker network inspect trion-sandbox >/dev/null 2>&1; then
        docker network rm trion-sandbox >/dev/null 2>&1 || note "Network still in use; skipped"
        ok "Network cleanup attempted"
    else
        skip "Network trion-sandbox not found"
    fi
fi
echo ""

log "Ensuring ${MEM_CONTAINER} is running for live DB cleanup..."
if $DOCKER_OK && ! running "$MEM_CONTAINER"; then
    exe docker compose -f "$COMPOSE_FILE" start "$MEM_CONTAINER"
    $OPT_DRY || sleep 2
fi

log "Clearing memory DB tables (live-safe transaction)..."
if $OPT_DRY; then
    skip "[dry-run] Would clear: ${MEM_SOFT_TABLES[*]}"
else
    PY_MEM_TABLES=$(py_list "${MEM_SOFT_TABLES[@]}")
    docker exec "$MEM_CONTAINER" python3 - <<PYEOF
import sqlite3
conn = sqlite3.connect("${MEM_DB}")
conn.execute("PRAGMA busy_timeout=5000")
tables = [${PY_MEM_TABLES}]
conn.execute("BEGIN IMMEDIATE")
for t in tables:
    try:
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        conn.execute(f"DELETE FROM {t}")
        print(f"  cleared {t}: {n} rows")
    except Exception as e:
        print(f"  skip {t}: {e}")
for fts in ("memory_fts", "memory_fts_data", "memory_fts_idx", "memory_fts_docsize", "memory_fts_config", "memory_fts_content"):
    try:
        conn.execute(f"DELETE FROM {fts}")
    except Exception:
        pass
try:
    conn.execute("DELETE FROM sqlite_sequence")
except Exception:
    pass
conn.commit()
conn.close()
print("  memory cleanup commit done")
PYEOF
    ok "Memory DB cleanup done"
fi
echo ""

log "Ensuring ${CMD_CONTAINER} is running for commander DB cleanup..."
if $DOCKER_OK && ! running "$CMD_CONTAINER"; then
    exe docker compose -f "$COMPOSE_FILE" start "$CMD_CONTAINER"
    $OPT_DRY || sleep 2
fi

log "Clearing commander DB tables..."
if $OPT_DRY; then
    skip "[dry-run] Soft tables: ${CMD_SOFT_TABLES[*]}"
    $OPT_HARD && skip "[dry-run] Hard tables: ${CMD_HARD_TABLES[*]}"
else
    if $OPT_HARD; then
        CMD_TABLES=("${CMD_SOFT_TABLES[@]}" "${CMD_HARD_TABLES[@]}")
    else
        CMD_TABLES=("${CMD_SOFT_TABLES[@]}")
    fi
    PY_CMD_TABLES=$(py_list "${CMD_TABLES[@]}")
    docker exec "$CMD_CONTAINER" python3 - <<PYEOF
import sqlite3
conn = sqlite3.connect("${CMD_DB}")
conn.execute("PRAGMA busy_timeout=5000")
tables = [${PY_CMD_TABLES}]
conn.execute("BEGIN IMMEDIATE")
for t in tables:
    try:
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        conn.execute(f"DELETE FROM {t}")
        print(f"  cleared {t}: {n} rows")
    except Exception as e:
        print(f"  skip {t}: {e}")
try:
    conn.execute("DELETE FROM sqlite_sequence")
except Exception:
    pass
conn.commit()
conn.close()
print("  commander cleanup commit done")
PYEOF
    ok "Commander DB cleanup done"
fi
echo ""

if $OPT_HARD && $OPT_RESEED; then
    log "Reseeding default blueprints..."
    if $OPT_DRY; then
        skip "[dry-run] Would run seed_default_blueprints()"
    else
        docker exec "$CMD_CONTAINER" python3 - <<'PYEOF'
from container_commander.blueprint_store import seed_default_blueprints
seed_default_blueprints()
print("  default blueprints seeded")
PYEOF
        ok "Default blueprints reseeded"
    fi
    echo ""
fi

if $OPT_HARD; then
    log "Clearing /trion-home (hard mode)..."
    if $OPT_DRY; then
        skip "[dry-run] Would remove /trion-home/*"
    else
        docker exec "$CMD_CONTAINER" sh -c 'rm -rf /trion-home/* /trion-home/.[!.]* 2>/dev/null || true'
        ok "/trion-home cleared"
    fi
    echo ""
fi

log "Removing digest artifacts on host..."
if $OPT_DRY; then
    skip "[dry-run] Would remove ${DIGEST_DIR}/*.csv"
    skip "[dry-run] Would remove ${DIGEST_DIR}/digest_state.json"
    skip "[dry-run] Would remove ${DIGEST_DIR}/digest.lock*"
else
    shopt -s nullglob
    _csvs=("${DIGEST_DIR}"/*.csv)
    if [ ${#_csvs[@]} -gt 0 ]; then
        rm -f "${_csvs[@]}"
        ok "Removed ${#_csvs[@]} digest CSV file(s)"
    else
        skip "No digest CSV files found"
    fi
    shopt -u nullglob
    rm -f \
        "${DIGEST_DIR}/digest_state.json" \
        "${DIGEST_DIR}/digest.lock" \
        "${DIGEST_DIR}/digest.lock.takeover" \
        "${DIGEST_DIR}/digest.lock.tmp" \
        2>/dev/null || true
    ok "Removed digest state + lock files"
fi
echo ""

if ! $OPT_KEEP_PROTOCOL; then
    log "Removing protocol artifacts (Agenten Arbeitsbereich) under memory/..."
    if $OPT_DRY; then
        skip "[dry-run] Would remove ${PROTOCOL_DIR}/*.md"
        skip "[dry-run] Would remove ${PROTOCOL_DIR}/.protocol_status.json and .daily_summary_status.json"
    else
        shopt -s nullglob
        _mds=("${PROTOCOL_DIR}"/*.md)
        if [ ${#_mds[@]} -gt 0 ]; then
            rm -f "${_mds[@]}"
            ok "Removed ${#_mds[@]} protocol markdown file(s)"
        else
            skip "No protocol markdown files found"
        fi
        shopt -u nullglob
        rm -f \
            "${PROTOCOL_DIR}/.protocol_status.json" \
            "${PROTOCOL_DIR}/.daily_summary_status.json" \
            2>/dev/null || true
        ok "Removed protocol status files (if present)"
    fi
    echo ""
fi

if $OPT_GITHUB; then
    log "GitHub-ready cleanup..."
    if $OPT_DRY; then
        skip "[dry-run] Would remove __pycache__, .pytest_cache, *.pyc"
        skip "[dry-run] Would remove *.bak, *.bak-*, *.backup, *.backup-*"
    else
        find "${COMPOSE_DIR}" -type d \( -name '__pycache__' -o -name '.pytest_cache' \) -exec rm -rf {} + 2>/dev/null || true
        find "${COMPOSE_DIR}" -type f \
            \( -name '*.pyc' -o -name '*.pyo' \
            -o -name '*.bak' -o -name '*.bak-*' \
            -o -name '*.backup' -o -name '*.backup-*' \
            -o -name '*.py.bak' -o -name '*.py.bak-*' \
            -o -name '*.yaml-backup' -o -name '*.yml-backup' \) -delete 2>/dev/null || true
        ok "GitHub artefact cleanup done"
    fi
    echo ""
fi

if ! $OPT_KEEP_DIGEST_WORKER; then
    log "Resuming digest-worker (if it was running before)..."
    if $OPT_DRY; then
        skip "[dry-run] Would start digest-worker if it was paused"
    else
        if $PAUSED_DIGEST; then
            docker compose -f "$COMPOSE_FILE" start "$DIGEST_WORKER" >/dev/null 2>&1 || note "Could not restart digest-worker"
            ok "digest-worker resumed"
        else
            skip "digest-worker was not paused"
        fi
    fi
    echo ""
fi

if ! $OPT_DRY; then
    log "Post-reset verification..."
    POST_CTRS=$(count_sandbox_ctrs)
    POST_VOLS=$(count_sandbox_vols)
    POST_MEM=$(count_rows "$MEM_CONTAINER" "$MEM_DB" memory)
    POST_FACTS=$(count_rows "$MEM_CONTAINER" "$MEM_DB" facts)
    POST_BP=$(count_rows "$CMD_CONTAINER" "$CMD_DB" blueprints)
    shopt -s nullglob
    _post_csvs=("${DIGEST_DIR}"/*.csv)
    POST_CSVS=${#_post_csvs[@]}
    shopt -u nullglob

    echo ""
    echo -e "  ${BOLD}Managed containers:${NC} ${POST_CTRS} (was ${PRE_SANDBOX_CTRS})"
    echo -e "  ${BOLD}Managed volumes:${NC}    ${POST_VOLS} (was ${PRE_SANDBOX_VOLS})"
    echo -e "  ${BOLD}Memory rows:${NC}       ${POST_MEM} (was ${PRE_MEM})"
    echo -e "  ${BOLD}Facts rows:${NC}        ${POST_FACTS} (was ${PRE_FACTS})"
    echo -e "  ${BOLD}Blueprint rows:${NC}    ${POST_BP} (was ${PRE_BP})"
    echo -e "  ${BOLD}Digest CSV files:${NC}  ${POST_CSVS} (was ${PRE_CSVS})"
fi

echo ""
if $OPT_DRY; then
    echo -e "${YELLOW}${BOLD}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}${BOLD}║ LIVE RESET DRY-RUN COMPLETE (no changes made)    ║${NC}"
    echo -e "${YELLOW}${BOLD}╚══════════════════════════════════════════════════╝${NC}"
else
    echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}${BOLD}║ TRION LIVE RESET COMPLETE ✓                      ║${NC}"
    echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════╝${NC}"
fi
echo ""
