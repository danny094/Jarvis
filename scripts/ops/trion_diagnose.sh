#!/usr/bin/env bash
# ============================================================
# scripts/ops/trion_diagnose.sh — TRION Runtime Diagnose
# ============================================================
# Goal:
#   Single entry-point diagnostics for runtime/ops issues.
#
# Modes:
#   --quick (default): core checks, fast output
#   --full           : includes additional log/error sampling
#
# Safety:
#   --fix-safe only runs low-risk actions (service up/restart/stop/create net+volume)
#   no destructive actions (no rm, no prune, no reset)
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
LOG_DIR="${REPO_ROOT}/logs"
NETWORK_NAME="big-bear-lobe-chat_default"

API_BASE_DEFAULT="http://localhost:8200"
WEB_BASE_DEFAULT="http://localhost:8400"
API_BASE="${TRION_ADMIN_API_BASE:-${API_BASE_DEFAULT}}"
WEB_BASE="${TRION_WEB_BASE:-${WEB_BASE_DEFAULT}}"

MODE="quick"
FIX_SAFE=false
EXPORT=false
NO_LOGS=false
SINCE="2h"
REDACT=false
YES=false

for arg in "$@"; do
  case "$arg" in
    --quick) MODE="quick" ;;
    --full) MODE="full" ;;
    --fix-safe) FIX_SAFE=true ;;
    --export) EXPORT=true ;;
    --no-logs) NO_LOGS=true ;;
    --redact) REDACT=true ;;
    --yes) YES=true ;;
    --since=*) SINCE="${arg#*=}" ;;
    -h|--help)
      cat <<'USAGE'
Usage: scripts/ops/trion_diagnose.sh [OPTIONS]

Modes:
  --quick              Fast core checks (default)
  --full               Include deeper log/error sampling

Actions:
  --fix-safe           Apply low-risk fixes (service up/restart/stop/create net/volume)
  --export             Write JSON report to logs/diagnose_report_*.json

Log controls:
  --no-logs            Skip service log sampling
  --since=<window>     Log window (default: 2h), e.g. 30m, 4h
  --redact             Redact basic IP/email patterns in sampled log text

Other:
  --yes                Skip fix-safe confirmation
  -h, --help           Show this help

Examples:
  bash scripts/ops/trion_diagnose.sh --quick
  bash scripts/ops/trion_diagnose.sh --full --export
  bash scripts/ops/trion_diagnose.sh --full --fix-safe --export --since=4h
USAGE
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

mkdir -p "${LOG_DIR}"
TMP_FINDINGS="$(mktemp)"
TMP_FIXES="$(mktemp)"
TMP_META="$(mktemp)"
TMP_LOGS_DIR="$(mktemp -d)"

cleanup() {
  rm -f "${TMP_FINDINGS}" "${TMP_FIXES}" "${TMP_META}" 2>/dev/null || true
  rm -rf "${TMP_LOGS_DIR}" 2>/dev/null || true
}
trap cleanup EXIT

PASS=0
INFO=0
LOW=0
MEDIUM=0
HIGH=0
CRITICAL=0

log()  { echo -e "${CYAN}[TRION-DIAG]${NC} $*"; }
ok()   { echo -e "  ${GREEN}OK${NC} $*"; }
warn() { echo -e "  ${YELLOW}WARN${NC} $*"; }
err()  { echo -e "  ${RED}ERR${NC} $*"; }

inc_sev() {
  case "$1" in
    PASS) PASS=$((PASS + 1)) ;;
    INFO) INFO=$((INFO + 1)) ;;
    LOW) LOW=$((LOW + 1)) ;;
    MEDIUM) MEDIUM=$((MEDIUM + 1)) ;;
    HIGH) HIGH=$((HIGH + 1)) ;;
    CRITICAL) CRITICAL=$((CRITICAL + 1)) ;;
  esac
}

add_meta() {
  local k="$1" v="$2"
  printf "%s\t%s\n" "$k" "$v" >> "${TMP_META}"
}

add_finding() {
  local sev="$1" code="$2" msg="$3" next="$4"
  printf "%s\t%s\t%s\t%s\n" "$sev" "$code" "$msg" "$next" >> "${TMP_FINDINGS}"
  inc_sev "$sev"
  case "$sev" in
    PASS) ok "[$code] $msg" ;;
    INFO|LOW) echo -e "  ${DIM}${sev}${NC} [$code] $msg" ;;
    MEDIUM|HIGH) warn "[$code] $msg" ;;
    CRITICAL) err "[$code] $msg" ;;
    *) echo "[$code] $msg" ;;
  esac
}

add_fix() {
  local cmd="$1" reason="$2"
  printf "%s\t%s\n" "$cmd" "$reason" >> "${TMP_FIXES}"
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

sanitize_line() {
  if ! $REDACT; then
    cat
    return
  fi
  sed -E \
    -e 's/[0-9]{1,3}(\.[0-9]{1,3}){3}/[REDACTED_IP]/g' \
    -e 's/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/[REDACTED_EMAIL]/g'
}

http_probe() {
  local url="$1" timeout_s="$2" out_file="$3" err_file="$4"
  local code
  code="$(curl -sS --max-time "$timeout_s" -o "$out_file" -w '%{http_code}' "$url" 2>"$err_file" || true)"
  echo "$code"
}

docker_ok=false
compose_ok=false
if have_cmd docker; then
  if docker info >/dev/null 2>&1; then
    docker_ok=true
  fi
fi
if have_cmd docker && docker compose version >/dev/null 2>&1; then
  compose_ok=true
fi

SERVICE_CONTAINERS=(
  jarvis-admin-api
  jarvis-webui
  mcp-sql-memory
  digest-worker
  cim-server
  sequential-thinking
  document-processor
  trion-skill-server
  tool-executor
  trion-runtime
  validator-service
  lobechat-adapter
)

log "Environment & identity"
add_meta "generated_at_utc" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
add_meta "repo_root" "${REPO_ROOT}"
add_meta "mode" "${MODE}"
add_meta "api_base" "${API_BASE}"
add_meta "web_base" "${WEB_BASE}"
add_meta "since" "${SINCE}"
add_meta "redact" "${REDACT}"
add_meta "compose_profiles" "${COMPOSE_PROFILES:-}"

if git -C "${REPO_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  sha="$(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  dirty_lines="$(git -C "${REPO_ROOT}" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
  add_meta "git_sha" "$sha"
  add_meta "git_dirty_lines" "$dirty_lines"
  add_finding "PASS" "GIT_IDENTITY" "git SHA=${sha}, dirty_lines=${dirty_lines}" "git status"
else
  add_finding "LOW" "GIT_IDENTITY" "Not a git working tree" ""
fi

if $docker_ok; then
  add_finding "PASS" "DOCKER_ACCESS" "Docker daemon reachable" ""
else
  add_finding "CRITICAL" "DOCKER_ACCESS" "Docker daemon unreachable" "sudo systemctl status docker"
  add_fix "docker compose -f '${COMPOSE_FILE}' up -d" "Attempt to bring stack up after daemon recovery"
fi

if ! $compose_ok; then
  add_finding "HIGH" "COMPOSE_PLUGIN" "docker compose plugin not available" "Install Docker Compose plugin"
else
  add_finding "PASS" "COMPOSE_PLUGIN" "docker compose available" ""
fi

# Whitelisted env snapshot
whitelist_env="$(env | grep -E '^(DIGEST_|TYPEDSTATE_|TRION_|COMPOSE_PROFILES=)' || true)"
if [ -n "${whitelist_env}" ]; then
  add_meta "env_whitelist" "$(echo "${whitelist_env}" | tr '\n' ';' | sed 's/;$/ /')"
  add_finding "PASS" "ENV_WHITELIST" "Captured whitelisted env keys" ""
else
  add_finding "INFO" "ENV_WHITELIST" "No whitelisted env vars present in current shell" ""
fi

log "Network, stack and service state"
if $docker_ok; then
  if docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
    add_finding "PASS" "NETWORK_PRESENT" "Network '${NETWORK_NAME}' exists" ""
  else
    add_finding "HIGH" "NETWORK_PRESENT" "Network '${NETWORK_NAME}' missing" "docker network create ${NETWORK_NAME}"
    add_fix "docker network create ${NETWORK_NAME}" "Create required external network"
  fi

  if docker volume inspect trion_home_data >/dev/null 2>&1; then
    add_finding "PASS" "HOME_VOLUME" "Volume 'trion_home_data' exists" ""
  else
    add_finding "HIGH" "HOME_VOLUME" "Volume 'trion_home_data' missing" "docker volume create trion_home_data"
    add_fix "docker volume create trion_home_data" "Create required external TRION home volume"
  fi

  if $compose_ok && [ -f "${COMPOSE_FILE}" ]; then
    ps_out="$(docker compose -f "${COMPOSE_FILE}" ps --format json 2>/dev/null || true)"
    if [ -n "${ps_out}" ]; then
      add_finding "PASS" "COMPOSE_PS" "Compose status readable" "docker compose -f ${COMPOSE_FILE} ps"
    else
      add_finding "MEDIUM" "COMPOSE_PS" "Could not read compose status as JSON" "docker compose -f ${COMPOSE_FILE} ps"
    fi
  fi

  restart_candidates=""
  for c in "${SERVICE_CONTAINERS[@]}"; do
    cid="$(docker ps -aq -f "name=^${c}$" 2>/dev/null | head -n1 || true)"
    if [ -z "${cid}" ]; then
      add_finding "LOW" "SERVICE_MISSING_${c}" "Container '${c}' not present" "docker compose -f ${COMPOSE_FILE} up -d ${c}"
      continue
    fi

    inspect_line="$(docker inspect --format '{{.Name}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.RestartCount}}|{{.Config.Image}}' "${cid}" 2>/dev/null || true)"
    name="$(echo "${inspect_line}" | cut -d'|' -f1 | sed 's#^/##')"
    state="$(echo "${inspect_line}" | cut -d'|' -f2)"
    health="$(echo "${inspect_line}" | cut -d'|' -f3)"
    exit_code="$(echo "${inspect_line}" | cut -d'|' -f4)"
    restart_count="$(echo "${inspect_line}" | cut -d'|' -f5)"
    image_ref="$(echo "${inspect_line}" | cut -d'|' -f6)"

    add_meta "service_${name}_state" "${state}"
    add_meta "service_${name}_health" "${health}"
    add_meta "service_${name}_restart_count" "${restart_count}"
    add_meta "service_${name}_image" "${image_ref}"

    if [ "${state}" != "running" ]; then
      add_finding "HIGH" "SERVICE_DOWN_${name}" "${name} state=${state} exit_code=${exit_code}" "docker compose -f ${COMPOSE_FILE} up -d ${name}"
      add_fix "docker compose -f '${COMPOSE_FILE}' up -d ${name}" "Start missing/stopped service ${name}"
    elif [ "${health}" = "unhealthy" ]; then
      add_finding "HIGH" "SERVICE_UNHEALTHY_${name}" "${name} unhealthy" "docker compose -f ${COMPOSE_FILE} restart ${name}"
      add_fix "docker compose -f '${COMPOSE_FILE}' restart ${name}" "Restart unhealthy service ${name}"
    else
      add_finding "PASS" "SERVICE_OK_${name}" "${name} running (health=${health})" ""
    fi

    if [ "${restart_count}" != "" ] && [ "${restart_count}" -gt 0 ] 2>/dev/null; then
      restart_candidates+="${restart_count}:${name} "
    fi
  done

  if [ -n "${restart_candidates}" ]; then
    top3="$(echo "${restart_candidates}" | tr ' ' '\n' | grep ':' | sort -t: -k1,1nr | head -n3 | tr '\n' ' ')"
    add_finding "MEDIUM" "RESTART_CANDIDATES" "Restart-loop candidates: ${top3}" "docker compose -f ${COMPOSE_FILE} ps"
    add_meta "restart_candidates_top3" "${top3}"
  fi
fi

log "Endpoint and runtime checks"
api_out="${TMP_LOGS_DIR}/api.out"
api_err="${TMP_LOGS_DIR}/api.err"
web_out="${TMP_LOGS_DIR}/web.out"
web_err="${TMP_LOGS_DIR}/web.err"
runtime_out="${TMP_LOGS_DIR}/runtime.out"
runtime_err="${TMP_LOGS_DIR}/runtime.err"

api_code="$(http_probe "${API_BASE}/health" 3 "${api_out}" "${api_err}")"
web_code="$(http_probe "${WEB_BASE}" 3 "${web_out}" "${web_err}")"

if [ "${api_code}" = "200" ]; then
  add_finding "PASS" "API_HEALTH" "Admin API reachable (${API_BASE}/health)" ""
else
  api_err_text="$(tr '\n' ' ' < "${api_err}" | sed 's/  */ /g')"
  add_finding "CRITICAL" "API_HEALTH" "Admin API unhealthy (code=${api_code}, err=${api_err_text:-none})" "docker compose -f ${COMPOSE_FILE} up -d jarvis-admin-api"
  add_fix "docker compose -f '${COMPOSE_FILE}' up -d jarvis-admin-api" "Bring Admin API up"
fi

if [ "${web_code}" = "200" ] || [ "${web_code}" = "304" ]; then
  add_finding "PASS" "WEB_HEALTH" "Web UI reachable (${WEB_BASE})" ""
else
  web_err_text="$(tr '\n' ' ' < "${web_err}" | sed 's/  */ /g')"
  add_finding "HIGH" "WEB_HEALTH" "Web UI not reachable (code=${web_code}, err=${web_err_text:-none})" "docker compose -f ${COMPOSE_FILE} up -d jarvis-webui"
  add_fix "docker compose -f '${COMPOSE_FILE}' up -d jarvis-webui" "Bring Web UI up"
fi

runtime_code="$(http_probe "${API_BASE}/api/runtime/digest-state" 5 "${runtime_out}" "${runtime_err}")"
runtime_json_ok=false
runtime_mode=""
runtime_digest_enable=""
runtime_daily=""
runtime_weekly=""
runtime_archive=""
runtime_jit_only=""

if [ "${runtime_code}" = "200" ]; then
  if python3 -m json.tool "${runtime_out}" >/dev/null 2>&1; then
    runtime_json_ok=true
    add_finding "PASS" "RUNTIME_ENDPOINT" "Runtime endpoint reachable and valid JSON" ""

    eval "$(python3 - "${runtime_out}" <<'PY'
import json,sys
p=sys.argv[1]
d=json.load(open(p,'r',encoding='utf-8'))
flags=d.get('flags',{}) if isinstance(d,dict) else {}
lock=d.get('locking',{}) if isinstance(d,dict) else {}
cu=d.get('catch_up',{}) if isinstance(d,dict) else {}
print(f"runtime_mode='{str(flags.get('digest_run_mode',''))}'")
print(f"runtime_digest_enable='{str(flags.get('digest_enable',''))}'")
print(f"runtime_daily='{str(flags.get('digest_daily_enable',''))}'")
print(f"runtime_weekly='{str(flags.get('digest_weekly_enable',''))}'")
print(f"runtime_archive='{str(flags.get('digest_archive_enable',''))}'")
print(f"runtime_jit_only='{str(d.get('jit_only',''))}'")
print(f"runtime_lock_status='{str(lock.get('status',''))}'")
print(f"runtime_lock_stale='{str(lock.get('stale',''))}'")
print(f"runtime_catchup_mode='{str(cu.get('mode',''))}'")
PY
)"

    add_meta "runtime_digest_run_mode" "${runtime_mode}"
    add_meta "runtime_digest_enable" "${runtime_digest_enable}"
    add_meta "runtime_jit_only" "${runtime_jit_only}"

    # Flag mismatch checks
    if [ "${runtime_digest_enable}" = "False" ] && { [ "${runtime_daily}" = "True" ] || [ "${runtime_weekly}" = "True" ] || [ "${runtime_archive}" = "True" ]; }; then
      add_finding "HIGH" "FLAG_MISMATCH_DIGEST_ENABLE" "digest_enable=false but sub-flags are enabled" "Align DIGEST_ENABLE and digest stage flags"
    fi

    if [ "${runtime_mode}" = "off" ]; then
      worker_count="$(docker ps --filter "name=^digest-worker$" --filter "status=running" -q 2>/dev/null | wc -l | tr -d ' ' || echo 0)"
      if [ "${worker_count}" -gt 0 ] 2>/dev/null; then
        add_finding "MEDIUM" "DIGEST_MODE_OFF_WITH_WORKER" "digest_run_mode=off but digest-worker is running" "docker compose -f ${COMPOSE_FILE} stop digest-worker"
        add_fix "docker compose -f '${COMPOSE_FILE}' stop digest-worker" "Stop digest-worker when mode=off"
      fi
    fi
  else
    add_finding "HIGH" "RUNTIME_ENDPOINT_JSON" "Runtime endpoint returned invalid JSON" "curl -s ${API_BASE}/api/runtime/digest-state"
  fi
else
  runtime_err_text="$(tr '\n' ' ' < "${runtime_err}" | sed 's/  */ /g')"
  add_finding "HIGH" "RUNTIME_ENDPOINT" "Runtime endpoint not reachable (code=${runtime_code}, err=${runtime_err_text:-none})" "curl -s ${API_BASE}/api/runtime/digest-state"
fi

log "Digest worker and lock plausibility"
if $docker_ok; then
  worker_running="$(docker ps --filter "name=^digest-worker$" --filter "status=running" -q 2>/dev/null | wc -l | tr -d ' ')"
  if [ "${worker_running}" = "1" ]; then
    add_finding "PASS" "DIGEST_WORKER_SINGLE" "Exactly one digest-worker running" ""
  elif [ "${worker_running}" = "0" ]; then
    if [ "${runtime_mode}" = "sidecar" ]; then
      add_finding "HIGH" "DIGEST_WORKER_MISSING" "run_mode=sidecar but digest-worker is not running" "docker compose -f ${COMPOSE_FILE} up -d digest-worker"
      add_fix "docker compose -f '${COMPOSE_FILE}' up -d digest-worker" "Start digest-worker in sidecar mode"
    else
      add_finding "INFO" "DIGEST_WORKER_OFF" "No digest-worker running" ""
    fi
  else
    add_finding "CRITICAL" "DIGEST_WORKER_DUPLICATE" "Multiple digest-worker instances running (${worker_running})" "docker ps --filter name=digest-worker"
  fi

  lock_path="${REPO_ROOT}/memory_speicher/digest.lock"
  takeover_path="${REPO_ROOT}/memory_speicher/digest.lock.takeover"
  if [ -f "${lock_path}" ]; then
    lock_age="$(python3 - <<PY
import os,time
p='${lock_path}'
print(int(time.time()-os.path.getmtime(p)))
PY
)"
    add_meta "digest_lock_age_s" "${lock_age}"
    if [ "${lock_age}" -gt 3600 ] 2>/dev/null; then
      add_finding "MEDIUM" "DIGEST_LOCK_AGE" "digest.lock age is high (${lock_age}s)" "bash scripts/ops/check_digest_state.sh"
    else
      add_finding "PASS" "DIGEST_LOCK_AGE" "digest.lock exists (age=${lock_age}s)" ""
    fi
  else
    add_finding "INFO" "DIGEST_LOCK" "digest.lock not present" ""
  fi

  if [ -f "${takeover_path}" ]; then
    add_finding "MEDIUM" "DIGEST_TAKEOVER_SENTINEL" "digest.lock.takeover exists (possible stale takeover marker)" "bash scripts/ops/check_digest_state.sh"
  else
    add_finding "PASS" "DIGEST_TAKEOVER_SENTINEL" "No takeover sentinel leftover" ""
  fi
fi

log "Storage and mount checks"
if df -P "${REPO_ROOT}" >/dev/null 2>&1; then
  use_pct="$(df -P "${REPO_ROOT}" | awk 'NR==2 {gsub("%","",$5); print $5}')"
  inode_pct="$(df -Pi "${REPO_ROOT}" | awk 'NR==2 {gsub("%","",$5); print $5}')"
  add_meta "disk_use_pct_repo" "${use_pct}"
  add_meta "inode_use_pct_repo" "${inode_pct}"

  if [ "${use_pct}" -ge 95 ] 2>/dev/null; then
    add_finding "CRITICAL" "DISK_SPACE" "Disk usage critical (${use_pct}%)" "df -h"
  elif [ "${use_pct}" -ge 90 ] 2>/dev/null; then
    add_finding "HIGH" "DISK_SPACE" "Disk usage high (${use_pct}%)" "df -h"
  else
    add_finding "PASS" "DISK_SPACE" "Disk usage OK (${use_pct}%)" ""
  fi

  if [ "${inode_pct}" -ge 95 ] 2>/dev/null; then
    add_finding "HIGH" "INODE_USE" "Inode usage high (${inode_pct}%)" "df -i"
  else
    add_finding "PASS" "INODE_USE" "Inode usage OK (${inode_pct}%)" ""
  fi
fi

if $docker_ok; then
  if docker system df >/dev/null 2>&1; then
    docker_df_line="$(docker system df 2>/dev/null | tr '\n' ';' | cut -c1-500)"
    add_meta "docker_system_df" "${docker_df_line}"
    add_finding "INFO" "DOCKER_DF" "Collected docker system df" "docker system df"
  fi

  admin_mounts="$(docker inspect -f '{{range .Mounts}}{{.Destination}}={{.Source}};{{end}}' jarvis-admin-api 2>/dev/null || true)"
  add_meta "admin_mounts" "${admin_mounts}"
  for m in /app/memory_speicher /app/memory /app/data /trion-home; do
    if echo "${admin_mounts}" | grep -Fq "${m}="; then
      add_finding "PASS" "MOUNT_${m//\//_}" "Mount present: ${m}" ""
    else
      add_finding "HIGH" "MOUNT_${m//\//_}" "Mount missing: ${m}" "docker inspect jarvis-admin-api"
    fi
  done
fi

log "Intra-container DNS checks"
if $docker_ok && docker ps --format '{{.Names}}' | grep -Fxq 'jarvis-admin-api'; then
  dns_res="$(docker exec -i jarvis-admin-api python3 - <<'PY' 2>/dev/null || true
import socket
for host in ('mcp-sql-memory','cim-server','sequential-thinking','document-processor'):
    try:
        ip=socket.gethostbyname(host)
        print(f"{host}={ip}")
    except Exception as e:
        print(f"{host}=ERR:{e}")
PY
)"
  add_meta "dns_resolution" "$(echo "${dns_res}" | tr '\n' ';')"
  if echo "${dns_res}" | grep -q 'ERR:'; then
    add_finding "HIGH" "DNS_RESOLUTION" "Admin container has DNS resolution errors" "docker network inspect ${NETWORK_NAME}"
  else
    add_finding "PASS" "DNS_RESOLUTION" "Admin container DNS resolution OK" ""
  fi
else
  add_finding "INFO" "DNS_RESOLUTION" "Skipped DNS check (jarvis-admin-api not running)" ""
fi

if [ "${MODE}" = "full" ] && ! $NO_LOGS && $docker_ok; then
  log "Log sampling"
  for svc in jarvis-admin-api mcp-sql-memory digest-worker; do
    if docker ps -a --format '{{.Names}}' | grep -Fxq "${svc}"; then
      log_file="${TMP_LOGS_DIR}/${svc}.log"
      if docker logs --since "${SINCE}" "${svc}" > "${log_file}" 2>&1; then
        if $REDACT; then
          sanitize_line < "${log_file}" > "${log_file}.redacted"
          mv "${log_file}.redacted" "${log_file}"
        fi
        err_count="$(grep -Ei 'error|exception|traceback|failed|critical' "${log_file}" | wc -l | tr -d ' ' || true)"
        add_meta "log_errors_${svc}" "${err_count}"
        if [ "${err_count}" -gt 0 ] 2>/dev/null; then
          sample="$(grep -Ei 'error|exception|traceback|failed|critical' "${log_file}" | head -n3 | tr '\n' ' ' | cut -c1-350 || true)"
          add_finding "MEDIUM" "LOG_ERRORS_${svc}" "${svc} shows ${err_count} error-like lines (sample: ${sample})" "docker logs --since ${SINCE} ${svc}"
        else
          add_finding "PASS" "LOG_ERRORS_${svc}" "${svc} log sample has no error-like lines" ""
        fi
      else
        add_finding "LOW" "LOG_SAMPLE_${svc}" "Could not collect logs for ${svc}" "docker logs ${svc}"
      fi
    fi
  done
elif $NO_LOGS; then
  add_finding "INFO" "LOGS_SKIPPED" "Log sampling skipped by --no-logs" ""
else
  add_finding "INFO" "LOGS_SKIPPED" "Log sampling skipped in quick mode" ""
fi

# Build fix plan (unique commands only)
if [ -s "${TMP_FIXES}" ]; then
  uniq_fixes="$(awk -F'\t' '!seen[$1]++ {print $1"\t"$2}' "${TMP_FIXES}")"
  printf "%s\n" "${uniq_fixes}" > "${TMP_FIXES}"
fi

if $FIX_SAFE; then
  if [ ! -s "${TMP_FIXES}" ]; then
    add_finding "INFO" "FIX_PLAN" "No safe fixes planned" ""
  else
    echo ""
    echo -e "${BOLD}Safe fix plan${NC}"
    awk -F'\t' '{print "  - " $2 " => " $1}' "${TMP_FIXES}"

    if ! $YES; then
      echo -ne "Type FIX_SAFE to execute: "
      read -r ans
      if [ "${ans}" != "FIX_SAFE" ]; then
        echo "Skipped safe fixes."
      else
        while IFS=$'\t' read -r cmd reason; do
          [ -z "${cmd}" ] && continue
          log "fix: ${reason}"
          bash -lc "${cmd}" >/dev/null 2>&1 || true
        done < "${TMP_FIXES}"
      fi
    else
      while IFS=$'\t' read -r cmd reason; do
        [ -z "${cmd}" ] && continue
        log "fix: ${reason}"
        bash -lc "${cmd}" >/dev/null 2>&1 || true
      done < "${TMP_FIXES}"
    fi

    # Minimal verify after fix
    v_api_out="${TMP_LOGS_DIR}/verify_api.out"
    v_api_err="${TMP_LOGS_DIR}/verify_api.err"
    v_api_code="$(http_probe "${API_BASE}/health" 3 "${v_api_out}" "${v_api_err}")"
    if [ "${v_api_code}" = "200" ]; then
      add_finding "PASS" "FIX_VERIFY_API" "Post-fix API health OK" ""
    else
      add_finding "HIGH" "FIX_VERIFY_API" "Post-fix API health still failing (code=${v_api_code})" "docker compose -f ${COMPOSE_FILE} ps"
    fi
  fi
fi

# Human summary + next commands
echo ""
echo -e "${BOLD}Summary${NC}"
echo "  CRITICAL=${CRITICAL} HIGH=${HIGH} MEDIUM=${MEDIUM} LOW=${LOW} INFO=${INFO} PASS=${PASS}"

if [ "${CRITICAL}" -gt 0 ]; then
  echo -e "${RED}Status: CRITICAL${NC}"
elif [ "${HIGH}" -gt 0 ]; then
  echo -e "${YELLOW}Status: HIGH${NC}"
elif [ "${MEDIUM}" -gt 0 ]; then
  echo -e "${YELLOW}Status: DEGRADED${NC}"
else
  echo -e "${GREEN}Status: HEALTHY${NC}"
fi

echo ""
echo -e "${BOLD}Suggested next commands${NC}"
next_count=0
while IFS=$'\t' read -r sev code msg next; do
  [ -z "${next}" ] && continue
  if [ "${sev}" = "CRITICAL" ] || [ "${sev}" = "HIGH" ] || [ "${sev}" = "MEDIUM" ]; then
    echo "  - ${next}"
    next_count=$((next_count + 1))
  fi
  [ "${next_count}" -ge 8 ] && break
done < <(awk -F'\t' 'BEGIN{OFS="\t"} {print $1,$2,$3,$4}' "${TMP_FINDINGS}")

if [ "${next_count}" -eq 0 ]; then
  echo "  - ./scripts/test_gate.sh full"
fi

if $EXPORT; then
  report_path="${LOG_DIR}/diagnose_report_$(date +%Y%m%d-%H%M%S).json"
  python3 - "${TMP_META}" "${TMP_FINDINGS}" "${TMP_FIXES}" "${report_path}" <<'PY'
import json,sys,datetime
meta_f,find_f,fix_f,out_f = sys.argv[1:]
meta={}
for line in open(meta_f,'r',encoding='utf-8'):
    line=line.rstrip('\n')
    if not line:
        continue
    k,v=(line.split('\t',1)+[''])[:2]
    meta[k]=v

findings=[]
summary={"CRITICAL":0,"HIGH":0,"MEDIUM":0,"LOW":0,"INFO":0,"PASS":0}
for line in open(find_f,'r',encoding='utf-8'):
    line=line.rstrip('\n')
    if not line:
        continue
    parts=(line.split('\t',3)+['','','',''])[:4]
    sev,code,msg,next_cmd=parts
    findings.append({
        "severity":sev,
        "code":code,
        "message":msg,
        "next_command":next_cmd,
    })
    summary[sev]=summary.get(sev,0)+1

fix_plan=[]
for line in open(fix_f,'r',encoding='utf-8'):
    line=line.rstrip('\n')
    if not line:
        continue
    cmd,reason=(line.split('\t',1)+[''])[:2]
    fix_plan.append({"cmd":cmd,"reason":reason})

status="healthy"
if summary.get("CRITICAL",0)>0:
    status="critical"
elif summary.get("HIGH",0)>0:
    status="high"
elif summary.get("MEDIUM",0)>0:
    status="degraded"

report={
    "generated_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "status":status,
    "summary":summary,
    "meta":meta,
    "findings":findings,
    "safe_fix_plan":fix_plan,
}
with open(out_f,'w',encoding='utf-8') as f:
    json.dump(report,f,indent=2)
print(out_f)
PY
  echo ""
  echo "Report: ${report_path}"
fi

# Exit semantics
if [ "${CRITICAL}" -gt 0 ]; then
  exit 2
fi
if [ "${HIGH}" -gt 0 ]; then
  exit 1
fi
exit 0
