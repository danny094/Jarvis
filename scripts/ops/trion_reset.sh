#!/usr/bin/env bash
# ============================================================
# scripts/ops/trion_reset.sh — TRION Factory Reset v2
# ============================================================
# Modes (combinable):
#   (default/--soft)  : DB tables (excl. blueprints) + digest artifacts
#                       + sandbox containers / volumes / network
#   --hard            : adds blueprints table + TRION home (/trion-home)
#   --reseed-blueprints : with --hard, re-seed default blueprints after wipe
#   --github-ready    : adds __pycache__, .pytest_cache, *.pyc, *.bak, *.backup-*
#   --dry-run         : print all actions, execute nothing
#
# Safety: two-step typed confirmation, set -euo pipefail,
#         label-based container filter (trion.managed=true)
# ============================================================
set -euo pipefail

# ── Colour palette ─────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# ── Constants ──────────────────────────────────────────────────────────────────
COMPOSE_DIR="/DATA/AppData/MCP/Jarvis/Jarvis"
COMPOSE_FILE="${COMPOSE_DIR}/docker-compose.yml"
TRION_LABEL="trion.managed=true"

MEM_CONTAINER="mcp-sql-memory"
MEM_DB="/app/data/memory.db"

CMD_CONTAINER="jarvis-admin-api"
CMD_DB="/app/data/commander.db"

DIGEST_DIR="${COMPOSE_DIR}/memory_speicher"

# Tables cleared in every reset (--soft is the default)
MEM_SOFT_TABLES=(memory facts embeddings graph_nodes graph_edges \
                 workspace_entries workspace_events \
                 task_active task_archive skill_metrics secrets)
CMD_SOFT_TABLES=(container_log secret_access_log)

# Additional tables cleared only in --hard
CMD_HARD_TABLES=(blueprints)

# Services to stop before reset; restart order after reset
SERVICES_STOP=(jarvis-admin-api digest-worker mcp-sql-memory)
SERVICES_START=(mcp-sql-memory jarvis-admin-api)

# ── Parse arguments ────────────────────────────────────────────────────────────
OPT_HARD=false
OPT_RESEED=false
OPT_GITHUB=false
OPT_DRY=false

for arg in "$@"; do
    case "$arg" in
        --soft)         ;;
        --hard)         OPT_HARD=true ;;
        --reseed-blueprints) OPT_RESEED=true ;;
        --github-ready) OPT_GITHUB=true ;;
        --dry-run)      OPT_DRY=true ;;
        -h|--help)
            cat <<EOF
Usage: $0 [OPTIONS]

Options:
  --soft          Reset DB tables (keep blueprints), digest artifacts,
                  sandbox containers/volumes/network  [default]
  --hard          Also delete blueprints + clear TRION home (/trion-home)
  --reseed-blueprints
                  With --hard: reseed default blueprints after wipe
  --github-ready  Also remove __pycache__, .pytest_cache, *.pyc, *.bak, *.backup-*
  --dry-run       Print all actions without executing anything
  -h, --help      Show this help

Examples:
  $0                             # soft reset
  $0 --hard                      # hard reset (delete blueprints + TRION home)
  $0 --hard --reseed-blueprints  # hard reset + reseed default blueprints
  $0 --github-ready              # soft + remove cache/temp files
  $0 --hard --github-ready       # full factory + github-ready cleanup
  $0 --dry-run --hard --reseed-blueprints --github-ready  # preview everything
EOF
            exit 0 ;;
        *)
            echo "Unknown option: $arg" >&2
            exit 1 ;;
    esac
done

# ── Helpers ────────────────────────────────────────────────────────────────────
log()  { echo -e "${CYAN}[TRION-RESET]${NC} $*"; }
ok()   { echo -e "  ${GREEN}✓${NC} $*"; }
skip() { echo -e "  ${DIM}→ $*${NC}"; }
note() { echo -e "  ${YELLOW}⚠${NC} $*"; }

# Execute or dry-run-print a simple command (no pipelines)
exe() {
    if $OPT_DRY; then
        echo -e "  ${DIM}[dry-run] $*${NC}"
        return 0
    fi
    "$@"
}

# Check if a container is running by name
running() { docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$1"; }

# Count rows in an SQLite table via docker exec (returns 0 on any failure)
count_rows() {
    local ctr="$1" db="$2" tbl="$3"
    docker exec "$ctr" python3 -c "
import sqlite3
try:
    print(sqlite3.connect('$db').execute('SELECT COUNT(*) FROM $tbl').fetchone()[0])
except:
    print(0)
" 2>/dev/null || echo 0
}

# Count sandbox containers (all states) and volumes filtered by TRION label
count_sandbox_ctrs() {
    (docker ps -aq --filter "label=${TRION_LABEL}" 2>/dev/null || true) | wc -l | tr -d ' '
}
count_sandbox_vols() {
    (docker volume ls -q --filter "label=${TRION_LABEL}" 2>/dev/null || true) | wc -l | tr -d ' '
}

# Build a Python list literal from a bash array: ('a','b','c')
py_list() {
    local IFS=','
    echo "'${*}'" | sed "s/,/','/g"
}

# ── Step 1: Collect pre-reset state ───────────────────────────────────────────
echo ""
echo -e "${RED}${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${RED}${BOLD}║            TRION  FACTORY  RESET   v2                   ║${NC}"
if $OPT_DRY; then
echo -e "${YELLOW}${BOLD}║                  ─── DRY-RUN ───                        ║${NC}"
fi
echo -e "${RED}${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

log "Collecting pre-reset state..."

PRE_SANDBOX_CTRS=$(count_sandbox_ctrs)
PRE_SANDBOX_VOLS=$(count_sandbox_vols)

if running "$MEM_CONTAINER"; then
    PRE_MEM=$(count_rows "$MEM_CONTAINER" "$MEM_DB" memory)
    PRE_FACTS=$(count_rows "$MEM_CONTAINER" "$MEM_DB" facts)
    PRE_NODES=$(count_rows "$MEM_CONTAINER" "$MEM_DB" graph_nodes)
    PRE_EDGES=$(count_rows "$MEM_CONTAINER" "$MEM_DB" graph_edges)
    PRE_WS=$(count_rows "$MEM_CONTAINER" "$MEM_DB" workspace_entries)
else
    PRE_MEM="?" PRE_FACTS="?" PRE_NODES="?" PRE_EDGES="?" PRE_WS="?"
fi

if running "$CMD_CONTAINER"; then
    PRE_BP=$(count_rows "$CMD_CONTAINER" "$CMD_DB" blueprints)
    PRE_CLOG=$(count_rows "$CMD_CONTAINER" "$CMD_DB" container_log)
else
    PRE_BP="?" PRE_CLOG="?"
fi

shopt -s nullglob
_csvs=("${DIGEST_DIR}"/*.csv)
PRE_CSVS=${#_csvs[@]}
shopt -u nullglob
PRE_STATE=$([ -f "${DIGEST_DIR}/digest_state.json" ] && echo "exists" || echo "absent")

# ── Step 2: Print action summary ───────────────────────────────────────────────
MODE_LABEL="--soft"
$OPT_HARD && MODE_LABEL="--hard"
$OPT_RESEED && MODE_LABEL+=" --reseed-blueprints"
$OPT_GITHUB && MODE_LABEL+=" --github-ready"
$OPT_DRY && MODE_LABEL+=" [DRY-RUN]"

echo -e "${BOLD}Mode:${NC} ${MODE_LABEL}"
echo ""
echo -e "${BOLD}Will be deleted:${NC}"
echo -e "  ${RED}•${NC} Memory tables  (memory=${PRE_MEM}, facts=${PRE_FACTS}, graph_nodes=${PRE_NODES}, graph_edges=${PRE_EDGES}, workspace_entries=${PRE_WS}, +6 more)"
echo -e "  ${RED}•${NC} Commander logs (container_log=${PRE_CLOG})"
echo -e "  ${RED}•${NC} Digest artifacts (${PRE_CSVS} CSV(s), digest_state=${PRE_STATE}, lock files)"
echo -e "  ${RED}•${NC} Sandbox containers (${PRE_SANDBOX_CTRS}) + volumes (${PRE_SANDBOX_VOLS}) [label=${TRION_LABEL}]"
echo -e "  ${RED}•${NC} Sandbox network (trion-sandbox)"
if $OPT_HARD; then
echo -e "  ${RED}•${NC} Blueprints (${PRE_BP} rows) [--hard]"
echo -e "  ${RED}•${NC} TRION home (/trion-home/*) [--hard]"
$OPT_RESEED && echo -e "  ${RED}•${NC} Re-seed default blueprints after wipe [--reseed-blueprints]"
fi
if $OPT_GITHUB; then
echo -e "  ${RED}•${NC} __pycache__, .pytest_cache, *.pyc, *.bak, *.backup-* [--github-ready]"
fi
echo ""
echo -e "${BOLD}Will be preserved:${NC}"
if ! $OPT_HARD; then
echo -e "  ${GREEN}•${NC} Blueprints (${PRE_BP} rows)"
fi
echo -e "  ${GREEN}•${NC} Daily protocol files (memory/*.md)"
echo -e "  ${GREEN}•${NC} All code, configs, docker-compose.yml"
echo ""

# ── Step 3: Confirmation ───────────────────────────────────────────────────────
if ! $OPT_DRY; then
    if $OPT_HARD; then
        echo -e "${RED}${BOLD}⚠  HARD RESET destroys blueprints and TRION home — this cannot be undone.${NC}"
        echo -ne "Type ${BOLD}HARD_RESET${NC} to confirm: "
        read -r confirm
        if [ "$confirm" != "HARD_RESET" ]; then
            echo -e "${GREEN}Aborted — no changes made.${NC}"
            exit 0
        fi
    else
        echo -ne "Type ${BOLD}RESET${NC} to confirm: "
        read -r confirm
        if [ "$confirm" != "RESET" ]; then
            echo -e "${GREEN}Aborted — no changes made.${NC}"
            exit 0
        fi
    fi
fi
echo ""

# ── Step 4: Stop services ──────────────────────────────────────────────────────
log "Stopping services..."
for svc in "${SERVICES_STOP[@]}"; do
    if running "$svc" || docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$svc"; then
        exe docker compose -f "$COMPOSE_FILE" stop "$svc"
        ok "Stopped $svc"
    else
        skip "$svc not running — skip"
    fi
done
echo ""

# ── Step 5: Remove sandbox containers ─────────────────────────────────────────
log "Removing sandbox containers (label=${TRION_LABEL})..."
if $OPT_DRY; then
    skip "[dry-run] Would remove containers with label=${TRION_LABEL}"
else
    SANDBOX_IDS=$(docker ps -aq --filter "label=${TRION_LABEL}" 2>/dev/null || true)
    if [ -n "$SANDBOX_IDS" ]; then
        # shellcheck disable=SC2086
        docker rm -f $SANDBOX_IDS
        ok "Removed sandbox containers"
    else
        skip "No sandbox containers found"
    fi
fi

# ── Step 6: Remove sandbox volumes ────────────────────────────────────────────
log "Removing sandbox volumes (label=${TRION_LABEL})..."
if $OPT_DRY; then
    skip "[dry-run] Would remove volumes with label=${TRION_LABEL}"
else
    SANDBOX_VOLS=$(docker volume ls -q --filter "label=${TRION_LABEL}" 2>/dev/null || true)
    if [ -n "$SANDBOX_VOLS" ]; then
        # shellcheck disable=SC2086
        docker volume rm $SANDBOX_VOLS
        ok "Removed sandbox volumes"
    else
        skip "No sandbox volumes found"
    fi
fi

# ── Step 7: Remove sandbox network ────────────────────────────────────────────
log "Removing sandbox network (trion-sandbox)..."
if $OPT_DRY; then
    skip "[dry-run] Would remove network trion-sandbox"
else
    if docker network inspect trion-sandbox >/dev/null 2>&1; then
        docker network rm trion-sandbox
        ok "Removed network trion-sandbox"
    else
        skip "Network trion-sandbox not found — skip"
    fi
fi
echo ""

# ── Step 8: Start memory DB container and clear tables ────────────────────────
log "Starting ${MEM_CONTAINER} for DB cleanup..."
exe docker compose -f "$COMPOSE_FILE" start "$MEM_CONTAINER"
if ! $OPT_DRY; then sleep 2; fi

log "Clearing memory DB tables..."
if $OPT_DRY; then
    skip "[dry-run] Would clear: ${MEM_SOFT_TABLES[*]}"
else
    PY_MEM_TABLES=$(py_list "${MEM_SOFT_TABLES[@]}")
    docker exec "$MEM_CONTAINER" python3 - <<PYEOF
import sqlite3
conn = sqlite3.connect("${MEM_DB}")
tables = [${PY_MEM_TABLES}]
for t in tables:
    try:
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        conn.execute(f"DELETE FROM {t}")
        print(f"  cleared {t}: {n} rows")
    except Exception as e:
        print(f"  skip {t}: {e}")
# FTS virtual tables (best-effort)
for fts in ("memory_fts", "memory_fts_data", "memory_fts_idx",
            "memory_fts_docsize", "memory_fts_config", "memory_fts_content"):
    try:
        conn.execute(f"DELETE FROM {fts}")
    except Exception:
        pass
try:
    conn.execute("DELETE FROM sqlite_sequence")
except Exception:
    pass
conn.commit()
conn.execute("VACUUM")
conn.close()
print("  VACUUM done")
PYEOF
    ok "Memory DB cleared"
fi
echo ""

# ── Step 9: Start commander container and clear tables ────────────────────────
log "Starting ${CMD_CONTAINER} for DB cleanup..."
exe docker compose -f "$COMPOSE_FILE" start "$CMD_CONTAINER"
if ! $OPT_DRY; then sleep 2; fi

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
tables = [${PY_CMD_TABLES}]
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
conn.execute("VACUUM")
conn.close()
print("  VACUUM done")
PYEOF
    ok "Commander DB cleared"
fi
echo ""

# ── Step 10: Digest artifacts (host filesystem) ────────────────────────────────
log "Removing digest artifacts..."
if $OPT_DRY; then
    skip "[dry-run] Would remove ${DIGEST_DIR}/*.csv"
    skip "[dry-run] Would remove ${DIGEST_DIR}/digest_state.json"
    skip "[dry-run] Would remove ${DIGEST_DIR}/digest.lock*"
else
    shopt -s nullglob
    csvs=("${DIGEST_DIR}"/*.csv)
    if [ ${#csvs[@]} -gt 0 ]; then
        rm -f "${csvs[@]}"
        ok "Removed ${#csvs[@]} CSV file(s)"
    else
        skip "No CSV files found in ${DIGEST_DIR}"
    fi
    shopt -u nullglob
    # State and lock files
    rm -f \
        "${DIGEST_DIR}/digest_state.json" \
        "${DIGEST_DIR}/digest.lock" \
        "${DIGEST_DIR}/digest.lock.takeover" \
        "${DIGEST_DIR}/digest.lock.tmp" \
        2>/dev/null || true
    ok "Removed digest_state.json + lock files (if present, incl. takeover sentinel)"
fi
echo ""

# ── Step 11: Optional blueprint reseed (--hard + --reseed-blueprints) ─────────
if $OPT_HARD && $OPT_RESEED; then
    log "[--hard --reseed-blueprints] Reseeding default blueprints..."
    if $OPT_DRY; then
        skip "[dry-run] Would run: seed_default_blueprints() in ${CMD_CONTAINER}"
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

# ── Step 12: TRION home (--hard only) ─────────────────────────────────────────
if $OPT_HARD; then
    log "[--hard] Clearing TRION home..."
    if $OPT_DRY; then
        skip "[dry-run] Would run: docker exec ${CMD_CONTAINER} rm -rf /trion-home/*"
    else
        docker exec "$CMD_CONTAINER" sh -c \
            'rm -rf /trion-home/* /trion-home/.[!.]* 2>/dev/null || true'
        ok "TRION home (/trion-home) cleared"
    fi
    echo ""
fi

# ── Step 13: GitHub-ready cleanup (--github-ready) ────────────────────────────
if $OPT_GITHUB; then
    log "[--github-ready] Removing cache and temp files..."
    if $OPT_DRY; then
        skip "[dry-run] Would remove __pycache__, .pytest_cache, *.pyc"
        skip "[dry-run] Would remove *.bak, *.bak-*, *.backup, *.backup-*"
    else
        find "${COMPOSE_DIR}" -type d \( -name '__pycache__' -o -name '.pytest_cache' \) \
            -exec rm -rf {} + 2>/dev/null || true
        find "${COMPOSE_DIR}" -type f \
            \( -name '*.pyc' -o -name '*.pyo' \
            -o -name '*.bak' -o -name '*.bak-*' \
            -o -name '*.backup' -o -name '*.backup-*' \
            -o -name '*.py.bak' -o -name '*.py.bak-*' \
            -o -name '*.yaml-backup' -o -name '*.yml-backup' \) \
            -delete 2>/dev/null || true
        ok "Cache and temp files removed"
    fi
    echo ""
fi

# ── Step 14: Restart services ─────────────────────────────────────────────────
log "Restarting services..."
for svc in "${SERVICES_START[@]}"; do
    exe docker compose -f "$COMPOSE_FILE" restart "$svc"
    ok "Restarted $svc"
done
if ! $OPT_DRY; then sleep 3; fi
echo ""

# ── Step 15: Post-reset verification ──────────────────────────────────────────
if ! $OPT_DRY; then
    log "Post-reset verification..."
    POST_CTRS=$(count_sandbox_ctrs)
    POST_MEM=$(count_rows "$MEM_CONTAINER" "$MEM_DB" memory)
    POST_FACTS=$(count_rows "$MEM_CONTAINER" "$MEM_DB" facts)
    POST_BP=$(count_rows "$CMD_CONTAINER" "$CMD_DB" blueprints)
    shopt -s nullglob
    _post_csvs=("${DIGEST_DIR}"/*.csv)
    POST_CSVS=${#_post_csvs[@]}
    shopt -u nullglob

    echo ""
    echo -e "  ${BOLD}Sandbox containers:${NC}  ${POST_CTRS}  (was ${PRE_SANDBOX_CTRS})"
    echo -e "  ${BOLD}Memory rows:${NC}         ${POST_MEM}  (was ${PRE_MEM})"
    echo -e "  ${BOLD}Facts rows:${NC}          ${POST_FACTS}  (was ${PRE_FACTS})"
    echo -e "  ${BOLD}Blueprints:${NC}          ${POST_BP}  (was ${PRE_BP})"
    echo -e "  ${BOLD}Digest CSVs:${NC}         ${POST_CSVS}  (was ${PRE_CSVS})"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
if $OPT_DRY; then
    echo -e "${YELLOW}${BOLD}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}${BOLD}║   DRY-RUN COMPLETE — no changes were made        ║${NC}"
    echo -e "${YELLOW}${BOLD}╚══════════════════════════════════════════════════╝${NC}"
else
    echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}${BOLD}║         TRION RESET COMPLETE  ✓                  ║${NC}"
    echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "Start a new chat to test with a fresh TRION!"
fi
echo ""
