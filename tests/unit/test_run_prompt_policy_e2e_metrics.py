import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_runner_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "run_prompt_policy_e2e.py"
    spec = importlib.util.spec_from_file_location("run_prompt_policy_e2e", str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_summarize_contains_kpis_and_cohorts():
    mod = _load_runner_module()
    results = [
        {
            "tags": [],
            "actual": {
                "approved": True,
                "tool_executed": True,
                "auto_answer_without_retry": True,
                "latency_ms": 100.0,
                "domain": "CONTAINER",
                "error": None,
            },
            "quality": {"score": 8, "domain_match": True, "approval_match": True, "needs_memory_match": None},
        },
        {
            "tags": ["real_autonomy"],
            "actual": {
                "approved": False,
                "tool_executed": False,
                "auto_answer_without_retry": False,
                "latency_ms": 300.0,
                "domain": "CONTAINER",
                "error": None,
            },
            "quality": {"score": 6, "domain_match": True, "approval_match": False, "needs_memory_match": None},
        },
    ]
    summary = mod._summarize(results)
    assert summary["total"] == 2
    assert summary["kpis"]["approved_rate"] == 0.5
    assert summary["kpis"]["blocked_rate"] == 0.5
    assert summary["kpis"]["tool_exec_rate"] == 0.5
    assert summary["cohorts"]["prompt_suite"]["total"] == 1
    assert summary["cohorts"]["real_autonomy"]["total"] == 1


def test_kpi_target_eval_detects_failures_against_baseline_and_targets():
    mod = _load_runner_module()
    summary = {
        "kpis": {
            "approved_rate": 0.80,
            "blocked_rate": 0.20,
            "tool_exec_rate": 0.40,
            "auto_answer_without_retry_rate": 0.30,
        }
    }
    baseline = {
        "kpis": {
            "approved_rate": 0.82,
            "blocked_rate": 0.30,
            "tool_exec_rate": 0.50,
            "auto_answer_without_retry_rate": 0.35,
        }
    }
    args = SimpleNamespace(
        target_approved_rate_min=0.85,
        target_blocked_rate_max=0.15,
        target_tool_exec_rate_min=0.45,
        target_auto_answer_without_retry_min=0.32,
        require_blocked_rate_improvement_pct=50.0,
        require_tool_exec_rate_improvement_pct=20.0,
    )
    failures = mod._evaluate_kpi_targets(summary=summary, baseline=baseline, args=args)
    assert len(failures) >= 4
    assert any("approved_rate" in f for f in failures)
    assert any("blocked_rate" in f for f in failures)
    assert any("tool_exec_rate" in f for f in failures)
