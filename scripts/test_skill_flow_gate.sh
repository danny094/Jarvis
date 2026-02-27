#!/usr/bin/env bash
# =============================================================================
# scripts/test_skill_flow_gate.sh — TRION Skill Flow Gate
# =============================================================================
#
# Goal:
#   End-to-end verification of the Skill roadmap flow (A0 → D/C10 rest)
#   with focused unit gates and optional rollback-flag matrix checks.
#
# Usage:
#   ./scripts/test_skill_flow_gate.sh               # full (default)
#   ./scripts/test_skill_flow_gate.sh quick         # fast core path
#   ./scripts/test_skill_flow_gate.sh full          # all skill-flow unit tests
#   ./scripts/test_skill_flow_gate.sh matrix        # rollback/flag matrix only
#   ./scripts/test_skill_flow_gate.sh all           # full + matrix
#   ./scripts/test_skill_flow_gate.sh --help
#
# Exit codes:
#   0 — all selected checks passed
#   1 — one or more checks failed
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

MODE="${1:-full}"
FAILED=0

info() { echo "[skill-gate] $*"; }
ok() { echo "[ OK ] $*"; }
fail() { echo "[FAIL] $*" >&2; FAILED=1; }
section() { echo ""; echo "━━━ $* ━━━"; }

run_step() {
    local label="$1"
    shift
    if "$@"; then
        ok "${label}"
    else
        fail "${label}"
    fi
}

run_pytest() {
    local label="$1"
    shift
    run_step "${label}" python -m pytest -q "$@" --tb=short
}

run_pytest_env() {
    local label="$1"
    shift
    local env_kv="$1"
    shift
    if env ${env_kv} python -m pytest -q "$@" --tb=short; then
        ok "${label}"
    else
        fail "${label}"
    fi
}

mini_control_sync_gate() {
    section "Mini Control Sync Gate"
    run_step "mini_control_core_parity_check" \
        python scripts/sync_mini_control_core.py --check
    run_pytest "mini_control_core_sync_test" \
        tests/unit/test_mini_control_core_sync.py
}

quick_gate() {
    section "Quick Skill Gate"
    mini_control_sync_gate
    run_pytest "c1_skill_detail_contract" \
        tests/unit/test_skill_detail_contract.py
    run_pytest "c2_skill_install_contract" \
        tests/unit/test_skill_install_contract.py
    run_pytest "c2_5_package_endpoint_contract" \
        tests/unit/test_package_endpoint_contract.py
    run_pytest "c6_single_truth_sync_stream" \
        tests/unit/test_single_truth_skill_context_sync_stream.py
    run_pytest "c10_budget_selection" \
        tests/unit/test_skill_selection_budget.py
    run_pytest "token_efficiency_pipeline" \
        tests/unit/test_token_efficiency_pipeline.py
}

full_gate() {
    section "Full Skill Gate"
    mini_control_sync_gate
    run_pytest "skill_flow_all_units" \
        tests/unit/test_skill_detail_contract.py \
        tests/unit/test_skill_install_contract.py \
        tests/unit/test_package_endpoint_contract.py \
        tests/unit/test_skill_truth_store.py \
        tests/unit/test_skill_keying.py \
        tests/unit/test_single_control_authority.py \
        tests/unit/test_typedstate_skills.py \
        tests/unit/test_single_truth_skill_context_sync_stream.py \
        tests/unit/test_skill_selection_budget.py \
        tests/unit/test_token_efficiency_pipeline.py \
        tests/unit/test_skill_package_policy.py \
        tests/unit/test_skill_secret_policy.py \
        tests/unit/test_secret_resolve_access_control.py \
        tests/unit/test_skill_graph_hygiene.py \
        tests/unit/test_skill_discovery_drift_parity.py \
        tests/unit/test_mini_control_core_sync.py
}

matrix_gate() {
    section "Rollback Flag Matrix"
    run_pytest_env "matrix_skill_context_renderer_legacy" \
        "SKILL_CONTEXT_RENDERER=legacy" \
        tests/unit/test_single_truth_skill_context_sync_stream.py
    run_pytest_env "matrix_skill_selection_mode_legacy" \
        "SKILL_SELECTION_MODE=legacy" \
        tests/unit/test_skill_selection_budget.py
    run_pytest_env "matrix_skill_package_install_manual_only" \
        "SKILL_PACKAGE_INSTALL_MODE=manual_only" \
        tests/unit/test_skill_package_policy.py
    run_pytest_env "matrix_skill_secret_enforcement_strict" \
        "SKILL_SECRET_ENFORCEMENT=strict" \
        tests/unit/test_skill_secret_policy.py \
        tests/unit/test_secret_resolve_access_control.py
    run_pytest_env "matrix_skill_graph_reconcile_false" \
        "SKILL_GRAPH_RECONCILE=false" \
        tests/unit/test_skill_graph_hygiene.py
    run_pytest_env "matrix_skill_discovery_disable" \
        "SKILL_DISCOVERY_ENABLE=false" \
        tests/unit/test_skill_discovery_drift_parity.py
     run_pytest_env "matrix_disable_skill_detail_api" \
         "ENABLE_SKILL_DETAIL_API=false" \
        tests/unit/test_skill_detail_contract.py::TestSkillDetailEndpoint::test_disabled_api_returns_404
 }

case "${MODE}" in
    quick)
        info "Mode: quick"
        quick_gate
        ;;
    full)
        info "Mode: full"
        full_gate
        ;;
    matrix)
        info "Mode: matrix"
        matrix_gate
        ;;
    all)
        info "Mode: all"
        full_gate
        matrix_gate
        ;;
    -h|--help|help)
        cat <<'EOF'
Usage:
  ./scripts/test_skill_flow_gate.sh [quick|full|matrix|all]

Modes:
  quick   Fast core skill-flow checks
  full    Full skill-flow unit gate (default)
  matrix  Rollback/feature-flag matrix checks
  all     full + matrix
EOF
        exit 0
        ;;
    *)
        echo "Unknown mode: ${MODE} (use quick|full|matrix|all)" >&2
        exit 1
        ;;
esac

echo ""
if [[ "${FAILED}" -eq 0 ]]; then
    echo "✓ Skill Flow Gate PASSED (${MODE})"
    exit 0
else
    echo "✗ Skill Flow Gate FAILED (${MODE}) — see errors above" >&2
    exit 1
fi
