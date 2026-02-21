#!/usr/bin/env bash
# scripts/ops/check_digest_state.sh
#
# Digest Pipeline — Ops Health Check
# Fetches /api/runtime/digest-state and prints a compact summary.
#
# Exit codes:
#   0  — healthy (all checks pass); also exit 0 when jq missing (fail-open)
#   1  — error: daily_digest.status=error OR locking.status=LOCKED+stale=true
#   3  — curl failed (API not reachable) or non-JSON response
#
# Usage:
#   bash scripts/ops/check_digest_state.sh [BASE_URL]
#   BASE_URL default: http://localhost:8200

set -euo pipefail

BASE_URL="${1:-http://localhost:8200}"
ENDPOINT="${BASE_URL}/api/runtime/digest-state"

# ── Prerequisites ─────────────────────────────────────────────────────────────

if ! command -v curl >/dev/null 2>&1; then
  echo "ERROR: curl not found" >&2
  exit 3
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "WARN: jq not found — printing raw JSON (fail-open)" >&2
  RAW=$(curl -sf --max-time 5 "${ENDPOINT}" 2>&1) || {
    echo "ERROR: cannot reach ${ENDPOINT}" >&2
    exit 3
  }
  echo "${RAW}"
  exit 0
fi

# ── Fetch ─────────────────────────────────────────────────────────────────────

RAW=$(curl -sf --max-time 5 "${ENDPOINT}" 2>&1) || {
  echo "ERROR: cannot reach ${ENDPOINT}" >&2
  exit 3
}

# Validate JSON
if ! echo "${RAW}" | jq empty 2>/dev/null; then
  echo "ERROR: non-JSON response from ${ENDPOINT}" >&2
  echo "${RAW}" | head -5
  exit 3
fi

# ── Parse ─────────────────────────────────────────────────────────────────────

# Detect API shape (v2 flat vs v1 nested)
IS_V2=$(echo "${RAW}" | jq 'has("daily_digest")' 2>/dev/null || echo "false")

if [ "${IS_V2}" = "true" ]; then
  DAILY_STATUS=$(echo  "${RAW}" | jq -r '.daily_digest.status  // "never"')
  WEEKLY_STATUS=$(echo "${RAW}" | jq -r '.weekly_digest.status // "never"')
  ARCHIVE_STATUS=$(echo "${RAW}" | jq -r '.archive_digest.status // "never"')
  LOCK_STATUS=$(echo   "${RAW}" | jq -r '.locking.status        // "FREE"')
  LOCK_OWNER=$(echo    "${RAW}" | jq -r '.locking.owner         // "null"')
  LOCK_STALE=$(echo    "${RAW}" | jq -r '.locking.stale         // "null"')
  CU_STATUS=$(echo     "${RAW}" | jq -r '.catch_up.status       // "never"')
  CU_MISSED=$(echo     "${RAW}" | jq -r '.catch_up.missed_runs  // "null"')
  CU_RECOVERED=$(echo  "${RAW}" | jq -r '.catch_up.recovered    // "null"')
  JIT_TRIGGER=$(echo   "${RAW}" | jq -r '.jit.trigger           // "null"')
  JIT_ROWS=$(echo      "${RAW}" | jq -r '.jit.rows              // "null"')
  JIT_ONLY=$(echo      "${RAW}" | jq -r '.jit_only              // false')
else
  # v1 legacy shape fallback
  DAILY_STATUS=$(echo  "${RAW}" | jq -r '.state.daily.status    // "never"')
  WEEKLY_STATUS=$(echo "${RAW}" | jq -r '.state.weekly.status   // "never"')
  ARCHIVE_STATUS=$(echo "${RAW}" | jq -r '.state.archive.status // "never"')
  LOCK_STATUS=$(echo   "${RAW}" | jq -r 'if .lock then "LOCKED" else "FREE" end')
  LOCK_OWNER=$(echo    "${RAW}" | jq -r '.lock.owner            // "null"')
  LOCK_STALE="null"
  CU_STATUS=$(echo     "${RAW}" | jq -r '.state.catch_up.status // "never"')
  CU_MISSED="null"
  CU_RECOVERED="null"
  JIT_TRIGGER=$(echo   "${RAW}" | jq -r '.state.jit.trigger     // "null"')
  JIT_ROWS=$(echo      "${RAW}" | jq -r '.state.jit.rows        // "null"')
  JIT_ONLY=$(echo      "${RAW}" | jq -r '.flags.jit_only        // false')
fi

DAILY_REASON=$(echo "${RAW}" | jq -r \
  'if has("daily_digest") then .daily_digest.reason // "null"
   else .state.daily.reason // "null" end' 2>/dev/null || echo "null")

# ── Display ───────────────────────────────────────────────────────────────────

echo "══════════════════════════════════════════════"
echo " Digest Pipeline State  —  $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo " Endpoint: ${ENDPOINT}"
echo "══════════════════════════════════════════════"

# Status coloring (terminal only, no-op in pipe)
_color() {
  local status="$1"
  local reset='\033[0m'
  case "${status}" in
    ok)      printf '\033[32m%s\033[0m' "${status}" ;;
    error)   printf '\033[31m%s\033[0m' "${status}" ;;
    skip)    printf '\033[33m%s\033[0m' "${status}" ;;
    never)   printf '\033[90m%s\033[0m' "${status}" ;;
    LOCKED)  printf '\033[31m%s\033[0m' "${status}" ;;
    FREE)    printf '\033[32m%s\033[0m' "${status}" ;;
    *)       printf '%s' "${status}" ;;
  esac
}

printf " %-16s  " "daily_digest:"
_color "${DAILY_STATUS}"; echo ""
[ "${DAILY_REASON}" != "null" ] && echo "   reason: ${DAILY_REASON}"

printf " %-16s  " "weekly_digest:"
_color "${WEEKLY_STATUS}"; echo ""

printf " %-16s  " "archive_digest:"
_color "${ARCHIVE_STATUS}"; echo ""

echo "──────────────────────────────────────────────"

printf " %-16s  " "locking:"
_color "${LOCK_STATUS}"
[ "${LOCK_OWNER}" != "null" ] && printf "  owner=%s" "${LOCK_OWNER}"
[ "${LOCK_STALE}"  = "true" ] && printf "  \033[31m[STALE]\033[0m"
echo ""

echo "──────────────────────────────────────────────"

printf " %-16s  status=%-8s  missed=%s  recovered=%s\n" \
  "catch_up:" "${CU_STATUS}" "${CU_MISSED}" "${CU_RECOVERED}"

printf " %-16s  jit_only=%-5s  trigger=%-20s  rows=%s\n" \
  "jit:" "${JIT_ONLY}" "${JIT_TRIGGER}" "${JIT_ROWS}"

echo "══════════════════════════════════════════════"

# ── Checks ────────────────────────────────────────────────────────────────────

EXIT_CODE=0
ALERTS=()

if [ "${DAILY_STATUS}" = "error" ]; then
  ALERTS+=("ALERT: daily_digest.status=error (reason: ${DAILY_REASON})")
  EXIT_CODE=1
fi

if [ "${LOCK_STATUS}" = "LOCKED" ] && [ "${LOCK_STALE}" = "true" ]; then
  ALERTS+=("ALERT: locking LOCKED+stale=true (owner: ${LOCK_OWNER}) — rm memory_speicher/digest.lock to recover")
  EXIT_CODE=1
fi

if [ ${#ALERTS[@]} -gt 0 ]; then
  echo ""
  for alert in "${ALERTS[@]}"; do
    echo " !! ${alert}"
  done
  echo ""
fi

[ ${EXIT_CODE} -eq 0 ] && echo " Status: OK" || echo " Status: DEGRADED (exit ${EXIT_CODE})"
echo ""
exit ${EXIT_CODE}
