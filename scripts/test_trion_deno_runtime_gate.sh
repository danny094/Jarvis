#!/usr/bin/env bash
# =============================================================================
# scripts/test_trion_deno_runtime_gate.sh
# =============================================================================
# Stable Deno runtime check for TRION:
# - prefer local deno when available
# - fallback to trion-runtime container when local deno is missing
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_FILE="${REPO_ROOT}/tests/trion/test_deno_runtime.ts"

if [[ ! -f "${TEST_FILE}" ]]; then
  echo "ERROR: Test file missing: ${TEST_FILE}" >&2
  exit 1
fi

if command -v deno >/dev/null 2>&1; then
  echo "[trion-deno-gate] running with local deno"
  deno test -A "${TEST_FILE}"
  exit 0
fi

echo "[trion-deno-gate] local deno missing, falling back to trion-runtime container"
docker exec trion-runtime deno --version >/dev/null

tmp_test="$(mktemp)"
cleanup() {
  rm -f "${tmp_test}" 2>/dev/null || true
  docker exec trion-runtime rm -f /tmp/test_deno_runtime.ts >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Rewrite import path for container runtime layout (/app/runtime).
sed 's#../../trion/runtime/plugin-host.ts#/app/runtime/plugin-host.ts#g' "${TEST_FILE}" > "${tmp_test}"

docker cp "${tmp_test}" trion-runtime:/tmp/test_deno_runtime.ts
docker exec trion-runtime sh -lc 'mkdir -p /tmp/deno-dir && DENO_DIR=/tmp/deno-dir deno test -A /tmp/test_deno_runtime.ts'
