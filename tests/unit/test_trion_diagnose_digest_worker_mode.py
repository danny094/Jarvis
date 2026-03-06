from pathlib import Path


def test_diagnose_treats_digest_worker_down_as_mode_dependent():
    root = Path(__file__).resolve().parents[2]
    src = (root / "scripts" / "ops" / "trion_diagnose.sh").read_text(encoding="utf-8")
    assert 'if [ "${name}" = "digest-worker" ]; then' in src
    assert "validated against digest_run_mode later" in src
    assert 'add_finding "INFO" "SERVICE_DOWN_${name}"' in src
