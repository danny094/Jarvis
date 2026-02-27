#!/usr/bin/env bash
# =============================================================================
# scripts/test_embedding_cpu_gate.sh — TRION CPU Embedding Pipeline Gate (Live)
# =============================================================================
#
# Goal:
#   Verify that embedding path runs in CPU mode end-to-end under live load.
#   This gate wraps the perf e2e and validates runtime/log evidence.
#
# Usage:
#   AI_TEST_LIVE=1 ./scripts/test_embedding_cpu_gate.sh
#   AI_TEST_LIVE=1 AI_PERF_BASE_URL=http://127.0.0.1:8200 ./scripts/test_embedding_cpu_gate.sh
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

if [[ "${AI_TEST_LIVE:-}" != "1" && "${AI_PERF_ENABLE:-}" != "1" ]]; then
  echo "ERROR: Set AI_TEST_LIVE=1 (or AI_PERF_ENABLE=1) for live CPU embedding gate." >&2
  exit 1
fi

TS="$(date +%Y%m%d-%H%M%S)"
SINCE_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

DEFAULT_REPORT="${REPO_ROOT}/logs/perf/embedding_cpu_gate_${TS}.json"
DEFAULT_SQL_LOG="${REPO_ROOT}/logs/perf/embedding_cpu_sql_memory_${TS}.log"
DEFAULT_ADMIN_LOG="${REPO_ROOT}/logs/perf/embedding_cpu_admin_api_${TS}.log"
DEFAULT_OLLAMA_LOG="${REPO_ROOT}/logs/perf/embedding_cpu_ollama_${TS}.log"

export AI_PERF_ENABLE="${AI_PERF_ENABLE:-1}"
export AI_TEST_LIVE="${AI_TEST_LIVE:-1}"
export AI_PERF_BASE_URL="${AI_PERF_BASE_URL:-${AI_TEST_TRION_URL:-${AI_TEST_BASE_URL:-http://127.0.0.1:8200}}}"
export AI_PERF_MODEL="${AI_PERF_MODEL:-${AI_TEST_MODEL:-ministral-3:8b}}"
export AI_PERF_RUNS="${AI_PERF_RUNS:-2}"
export AI_PERF_WARMUP="${AI_PERF_WARMUP:-0}"
export AI_PERF_TIMEOUT_S="${AI_PERF_TIMEOUT_S:-120}"
export AI_PERF_HEALTH_TIMEOUT_S="${AI_PERF_HEALTH_TIMEOUT_S:-15}"
export AI_PERF_HEALTH_RETRIES="${AI_PERF_HEALTH_RETRIES:-2}"
export AI_PERF_MAX_RETRIES="${AI_PERF_MAX_RETRIES:-1}"
export AI_PERF_MAX_ERROR_RATE="${AI_PERF_MAX_ERROR_RATE:-0.50}"
export AI_PERF_REPORT="${AI_PERF_REPORT:-${DEFAULT_REPORT}}"
export AI_PERF_EMBED_CPU_ONLY=1
export AI_PERF_FORCE_ROUTING_EMBEDDING_AUTO=1
export AI_PERF_REQUIRE_ROUTING_EVIDENCE="${AI_PERF_REQUIRE_ROUTING_EVIDENCE:-1}"
export AI_PERF_SQL_MEMORY_CONTAINER="${AI_PERF_SQL_MEMORY_CONTAINER:-mcp-sql-memory}"
export AI_PERF_ADMIN_API_CONTAINER="${AI_PERF_ADMIN_API_CONTAINER:-jarvis-admin-api}"
export AI_PERF_OLLAMA_CONTAINER="${AI_PERF_OLLAMA_CONTAINER:-ollama}"

if [[ -z "${AI_PERF_PROMPTS_JSON:-}" ]]; then
  export AI_PERF_PROMPTS_JSON='[
    "Merke dir diese Notiz: CPU embedding gate probe alpha 2026.",
    "Fasse die zuletzt gemerkte Notiz in einem Satz zusammen.",
    "Nenne kurz zwei Risiken bei GPU-VRAM-Engpass in einer LLM-Pipeline."
  ]'
fi

mkdir -p "$(dirname "${AI_PERF_REPORT}")"

echo "[cpu-embed-gate] base_url=${AI_PERF_BASE_URL}"
echo "[cpu-embed-gate] model=${AI_PERF_MODEL}"
echo "[cpu-embed-gate] warmup=${AI_PERF_WARMUP} runs=${AI_PERF_RUNS} retries=${AI_PERF_MAX_RETRIES}"
echo "[cpu-embed-gate] sql_memory_container=${AI_PERF_SQL_MEMORY_CONTAINER} admin_api_container=${AI_PERF_ADMIN_API_CONTAINER} ollama_container=${AI_PERF_OLLAMA_CONTAINER}"
echo "[cpu-embed-gate] since_utc=${SINCE_UTC}"

./scripts/test_skill_perf_gate.sh

python - "${AI_PERF_REPORT}" <<'PY'
import json
import pathlib
import sys

report_path = pathlib.Path(sys.argv[1])
if not report_path.exists():
    raise SystemExit(f"Report missing: {report_path}")

data = json.loads(report_path.read_text(encoding="utf-8"))
meta = data.get("meta", {})
state = meta.get("embedding_cpu_mode", {}) or {}
if not state.get("enabled"):
    raise SystemExit("embedding_cpu_mode.enabled is false")
if not state.get("prepare_ok"):
    raise SystemExit("embedding_cpu_mode.prepare_ok is false")
if state.get("after_policy") != "cpu_only":
    raise SystemExit(f"embedding_cpu_mode.after_policy expected cpu_only, got {state.get('after_policy')!r}")
if not state.get("restore_ok"):
    raise SystemExit("embedding_cpu_mode.restore_ok is false")
print(f"[cpu-embed-gate] report_ok={report_path}")
PY

SQL_LOG_PATH="${AI_PERF_SQL_LOG_PATH:-${DEFAULT_SQL_LOG}}"
ROUTING_EVIDENCE_OK=0
if docker ps --filter "name=^/${AI_PERF_SQL_MEMORY_CONTAINER}$" --format '{{.Names}}' | rg -q "^${AI_PERF_SQL_MEMORY_CONTAINER}$"; then
  docker logs --since "${SINCE_UTC}" "${AI_PERF_SQL_MEMORY_CONTAINER}" > "${SQL_LOG_PATH}" 2>&1 || true
  if [[ -s "${SQL_LOG_PATH}" ]] && rg -q "role=sql_memory_embedding.*policy=cpu_only" "${SQL_LOG_PATH}" && rg -q "role=sql_memory_embedding.*effective_target=cpu" "${SQL_LOG_PATH}"; then
    ROUTING_EVIDENCE_OK=1
    echo "[cpu-embed-gate] sql_memory_log_ok=${SQL_LOG_PATH}"
  else
    echo "[cpu-embed-gate] WARN: no cpu routing evidence in sql-memory logs (${SQL_LOG_PATH})" >&2
  fi
  if rg -q "role=sql_memory_embedding.*effective_target=gpu" "${SQL_LOG_PATH}"; then
    echo "[cpu-embed-gate] ERROR: found GPU target in sql-memory logs during CPU gate (${SQL_LOG_PATH})" >&2
    exit 1
  fi
else
  echo "[cpu-embed-gate] WARN: container not running: ${AI_PERF_SQL_MEMORY_CONTAINER}" >&2
fi

ADMIN_LOG_PATH="${AI_PERF_ADMIN_LOG_PATH:-${DEFAULT_ADMIN_LOG}}"
if [[ "${ROUTING_EVIDENCE_OK}" -ne 1 ]]; then
  if docker ps --filter "name=^/${AI_PERF_ADMIN_API_CONTAINER}$" --format '{{.Names}}' | rg -q "^${AI_PERF_ADMIN_API_CONTAINER}$"; then
    docker logs --since "${SINCE_UTC}" "${AI_PERF_ADMIN_API_CONTAINER}" > "${ADMIN_LOG_PATH}" 2>&1 || true
    if [[ -s "${ADMIN_LOG_PATH}" ]] && rg -q "role=(archive_embedding|sql_memory_embedding).*policy=cpu_only" "${ADMIN_LOG_PATH}" && rg -q "role=(archive_embedding|sql_memory_embedding).*effective_target=cpu" "${ADMIN_LOG_PATH}"; then
      ROUTING_EVIDENCE_OK=1
      echo "[cpu-embed-gate] admin_api_log_ok=${ADMIN_LOG_PATH}"
    else
      echo "[cpu-embed-gate] WARN: no cpu routing evidence in admin-api logs (${ADMIN_LOG_PATH})" >&2
    fi
    if rg -q "role=(archive_embedding|sql_memory_embedding).*effective_target=gpu" "${ADMIN_LOG_PATH}"; then
      echo "[cpu-embed-gate] ERROR: found GPU target in admin-api embedding logs during CPU gate (${ADMIN_LOG_PATH})" >&2
      exit 1
    fi
  else
    echo "[cpu-embed-gate] WARN: container not running: ${AI_PERF_ADMIN_API_CONTAINER}" >&2
  fi
fi

if [[ "${ROUTING_EVIDENCE_OK}" -ne 1 ]]; then
  echo "[cpu-embed-gate] ERROR: no routing evidence for cpu_only embedding target found" >&2
  [[ "${AI_PERF_REQUIRE_ROUTING_EVIDENCE}" == "1" ]] && exit 1
fi

OLLAMA_LOG_PATH="${AI_PERF_OLLAMA_LOG_PATH:-${DEFAULT_OLLAMA_LOG}}"
if docker ps --filter "name=^/${AI_PERF_OLLAMA_CONTAINER}$" --format '{{.Names}}' | rg -q "^${AI_PERF_OLLAMA_CONTAINER}$"; then
  docker logs --since "${SINCE_UTC}" "${AI_PERF_OLLAMA_CONTAINER}" > "${OLLAMA_LOG_PATH}" 2>&1 || true
  UNLOAD_COUNT="$(rg -i -c 'unload|evict|unloading model' "${OLLAMA_LOG_PATH}" 2>/dev/null || echo 0)"
  echo "[cpu-embed-gate] ollama_unload_events=${UNLOAD_COUNT} log=${OLLAMA_LOG_PATH}"
else
  echo "[cpu-embed-gate] WARN: container not running: ${AI_PERF_OLLAMA_CONTAINER}" >&2
fi

echo ""
echo "✓ CPU Embedding Gate PASSED"
echo "Report: ${AI_PERF_REPORT}"
