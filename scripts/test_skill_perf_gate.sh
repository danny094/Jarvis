#!/usr/bin/env bash
# =============================================================================
# scripts/test_skill_perf_gate.sh — TRION Skill Perf Gate (Live)
# =============================================================================
#
# Runs live perf probe against /api/chat and writes a JSON report.
#
# Usage:
#   ./scripts/test_skill_perf_gate.sh
#   AI_TEST_LIVE=1 AI_PERF_BASE_URL=http://127.0.0.1:8200 ./scripts/test_skill_perf_gate.sh
#   AI_TEST_LIVE=1 AI_PERF_BASELINE=logs/perf/baseline.json ./scripts/test_skill_perf_gate.sh
#
# Notes:
#   - Requires a reachable API endpoint (default: http://127.0.0.1:8200)
#   - Uses tests/e2e/test_ai_pipeline_perf.py
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

# Opt-in guard (mirrors existing live-gate style)
if [[ "${AI_TEST_LIVE:-}" != "1" && "${AI_PERF_ENABLE:-}" != "1" ]]; then
  echo "ERROR: Set AI_TEST_LIVE=1 (or AI_PERF_ENABLE=1) to run live perf gate." >&2
  echo "Example:" >&2
  echo "  AI_TEST_LIVE=1 AI_PERF_BASE_URL=http://127.0.0.1:8200 ./scripts/test_skill_perf_gate.sh" >&2
  exit 1
fi

TS="$(date +%Y%m%d-%H%M%S)"
DEFAULT_REPORT="${REPO_ROOT}/logs/perf/skill_perf_report_${TS}.json"

# Reasonable defaults; override via env as needed.
export AI_PERF_ENABLE="${AI_PERF_ENABLE:-1}"
export AI_PERF_BASE_URL="${AI_PERF_BASE_URL:-${AI_TEST_TRION_URL:-${AI_TEST_BASE_URL:-http://127.0.0.1:8200}}}"
export AI_PERF_MODEL="${AI_PERF_MODEL:-${AI_TEST_MODEL:-ministral-3:8b}}"
export AI_PERF_RUNS="${AI_PERF_RUNS:-6}"
export AI_PERF_WARMUP="${AI_PERF_WARMUP:-2}"
export AI_PERF_TIMEOUT_S="${AI_PERF_TIMEOUT_S:-120}"
export AI_PERF_HEALTH_TIMEOUT_S="${AI_PERF_HEALTH_TIMEOUT_S:-15}"
export AI_PERF_HEALTH_RETRIES="${AI_PERF_HEALTH_RETRIES:-2}"
export AI_PERF_MAX_RETRIES="${AI_PERF_MAX_RETRIES:-1}"
export AI_PERF_MAX_ERROR_RATE="${AI_PERF_MAX_ERROR_RATE:-0.30}"
export AI_PERF_REPORT="${AI_PERF_REPORT:-${DEFAULT_REPORT}}"
export AI_PERF_EMBED_CPU_ONLY="${AI_PERF_EMBED_CPU_ONLY:-0}"
export AI_PERF_FORCE_ROUTING_EMBEDDING_AUTO="${AI_PERF_FORCE_ROUTING_EMBEDDING_AUTO:-1}"

# Gate thresholds (tune per hardware/model)
export AI_PERF_MAX_P95_E2E_MS="${AI_PERF_MAX_P95_E2E_MS:-20000}"
export AI_PERF_MAX_P95_TTFT_MS="${AI_PERF_MAX_P95_TTFT_MS:-8000}"
export AI_PERF_MIN_P50_TPS="${AI_PERF_MIN_P50_TPS:-2}"
export AI_PERF_MAX_P95_TOTAL_TOKENS="${AI_PERF_MAX_P95_TOTAL_TOKENS:-0}"
export AI_PERF_MAX_REGRESSION_PCT="${AI_PERF_MAX_REGRESSION_PCT:-15}"

mkdir -p "$(dirname "${AI_PERF_REPORT}")"

echo "[skill-perf] base_url=${AI_PERF_BASE_URL}"
echo "[skill-perf] model=${AI_PERF_MODEL}"
echo "[skill-perf] embedding_cpu_only=${AI_PERF_EMBED_CPU_ONLY} force_embedding_auto_route=${AI_PERF_FORCE_ROUTING_EMBEDDING_AUTO}"
echo "[skill-perf] warmup=${AI_PERF_WARMUP} runs=${AI_PERF_RUNS} retries=${AI_PERF_MAX_RETRIES} max_error_rate=${AI_PERF_MAX_ERROR_RATE}"
echo "[skill-perf] thresholds: p95_e2e<=${AI_PERF_MAX_P95_E2E_MS}ms p95_ttft<=${AI_PERF_MAX_P95_TTFT_MS}ms p50_tps>=${AI_PERF_MIN_P50_TPS}"
if [[ -n "${AI_PERF_BASELINE:-}" ]]; then
  echo "[skill-perf] baseline=${AI_PERF_BASELINE} max_regression=${AI_PERF_MAX_REGRESSION_PCT}%"
fi

python -m pytest -q tests/e2e/test_ai_pipeline_perf.py -s --tb=short

echo ""
echo "✓ Skill Perf Gate PASSED"
echo "Report: ${AI_PERF_REPORT}"
