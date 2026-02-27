#!/usr/bin/env bash
# =============================================================================
# scripts/test_gate.sh — TRION Test Gate
# =============================================================================
#
# Usage:
#   ./scripts/test_gate.sh             # Quick Gate (default)
#   ./scripts/test_gate.sh full        # Full Gate
#   ./scripts/test_gate.sh live        # Nightly Live Gate (requires AI_TEST_LIVE=1)
#   ./scripts/test_gate.sh dataset     # Dataset validation only
#
# Exit codes:
#   0 — all checks passed
#   1 — one or more checks failed
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

MODE="${1:-quick}"
FAILED=0

# ── Helpers ─────────────────────────────────────────────────────────────────

info()  { echo "[gate] $*"; }
fail()  { echo "[FAIL] $*" >&2; FAILED=1; }
ok()    { echo "[ OK ] $*"; }
section(){ echo ""; echo "━━━ $* ━━━"; }

run_step() {
    local label="$1"; shift
    if "$@"; then
        ok "$label"
    else
        fail "$label"
    fi
}

# ── Dataset Validation ───────────────────────────────────────────────────────

dataset_gate() {
    section "Dataset Validation"
    run_step "validate_test_dataset" \
        python tools/validate_test_dataset.py
}

# ── Quick Gate ───────────────────────────────────────────────────────────────
# Target: < 5 minutes
# Scope:  dataset + harness smoke + sync/stream parity smoke

quick_gate() {
    section "Quick Gate"

    dataset_gate

    section "Mini Control Sync Gate"
    run_step "mini_control_core_parity_check" \
        python scripts/sync_mini_control_core.py --check
    run_step "mini_control_core_sync_test" \
        python -m pytest -q tests/unit/test_mini_control_core_sync.py --tb=short

    info "Running harness smoke tests..."
    run_step "harness_smoke" \
        python -m pytest -q \
            tests/e2e/test_ai_pipeline_sync_stream.py::TestSyncStreamParity::test_parity_assembled_text \
            tests/e2e/test_ai_pipeline_sync_stream.py::TestContextMarkers \
            tests/e2e/test_ai_pipeline_sync_stream.py::TestStreamEventStructure \
            tests/e2e/test_memory_roundtrip.py::TestMemoryRoundtrip::test_store_request_succeeds \
            tests/e2e/test_memory_roundtrip.py::TestMemoryRoundtrip::test_recall_request_succeeds \
            --tb=short

    info "Running golden regression smoke..."
    run_step "golden_regression_smoke" \
        python -m pytest -q \
            tests/e2e/test_golden_regression.py::TestNormalizerStability \
            tests/e2e/test_golden_regression.py::TestGoldenPhase0 \
            --tb=short
}

# ── Full Gate ─────────────────────────────────────────────────────────────────
# Scope: all unit + all new E2E/phase tests

full_gate() {
    quick_gate

    section "Core Unit Tests"
    run_step "core_unit_tests" \
        python -m pytest -q \
            tests/unit/test_single_truth_channel.py \
            tests/unit/test_orchestrator_context_pipeline.py \
            tests/unit/test_context_cleanup_phase2.py \
            tests/unit/test_phase15_budgeting.py \
            tests/unit/test_container_restart_recovery.py \
            tests/unit/test_graph_hygiene.py \
            tests/unit/test_graph_hygiene_commit4.py \
            --tb=short

    section "E2E Phase Tests"
    run_step "e2e_phase_tests" \
        python -m pytest -q \
            tests/e2e/test_ai_pipeline_sync_stream.py \
            tests/e2e/test_memory_roundtrip.py \
            tests/e2e/test_golden_regression.py \
            tests/e2e/test_phase2_dedup.py \
            tests/e2e/test_phase3_typedstate.py \
            tests/e2e/test_phase4_recovery.py \
            tests/e2e/test_phase5_graph_hygiene.py \
            --tb=short

    section "Phase 6 Security Tests"
    run_step "p6_security_tests" \
        python -m pytest -q \
            tests/unit/test_phase6_security.py \
            --tb=short
}

# ── Nightly Live Gate ─────────────────────────────────────────────────────────
# Requires: AI_TEST_LIVE=1  AI_TEST_BASE_URL=http://...

live_gate() {
    section "Nightly Live Gate"

    if [[ "${AI_TEST_LIVE:-}" != "1" ]]; then
        echo "ERROR: AI_TEST_LIVE=1 is required for the live gate." >&2
        echo "  Set: export AI_TEST_LIVE=1 AI_TEST_BASE_URL=http://localhost:11434" >&2
        exit 1
    fi

    info "Live backend: ${AI_TEST_BASE_URL:-unset}"

    run_step "live_sync_stream_parity" \
        python -m pytest -q \
            tests/e2e/test_ai_pipeline_sync_stream.py \
            --tb=short

    run_step "live_golden_regression" \
        python -m pytest -q \
            tests/e2e/test_golden_regression.py \
            --tb=short
}

# ── Dispatch ─────────────────────────────────────────────────────────────────

info "Gate mode: $MODE"
info "Repo root: $REPO_ROOT"

case "$MODE" in
    quick)    quick_gate ;;
    full)     full_gate ;;
    live)     live_gate ;;
    dataset)  dataset_gate ;;
    *)
        echo "Unknown mode: $MODE (use: quick | full | live | dataset)" >&2
        exit 1
        ;;
esac

echo ""
if [[ $FAILED -eq 0 ]]; then
    echo "✓ Gate PASSED ($MODE)"
    exit 0
else
    echo "✗ Gate FAILED ($MODE) — see errors above" >&2
    exit 1
fi
