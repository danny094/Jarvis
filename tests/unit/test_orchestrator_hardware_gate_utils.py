from core.orchestrator_hardware_gate_utils import check_hardware_gate_early


def test_check_hardware_gate_early_ignores_non_skill_tasks():
    out = check_hardware_gate_early(
        "bitte 30b modell bauen",
        {"suggested_tools": ["run_skill"], "intent": "build"},
        hardware_gate_patterns=("30b",),
        get_gpu_status_fn=lambda: "8 GB",
    )
    assert out is None


def test_check_hardware_gate_early_ignores_when_no_pattern_match():
    out = check_hardware_gate_early(
        "bitte skill erstellen",
        {"suggested_tools": ["autonomous_skill_task"], "intent": "create skill"},
        hardware_gate_patterns=("30b",),
        get_gpu_status_fn=lambda: "8 GB",
    )
    assert out is None


def test_check_hardware_gate_early_builds_block_message_with_gpu_status():
    out = check_hardware_gate_early(
        "baue 30b modell",
        {"suggested_tools": ["autonomous_skill_task"], "intent": "30b model"},
        hardware_gate_patterns=("30b",),
        get_gpu_status_fn=lambda: "NVIDIA RTX 2060 SUPER, 8 GB",
    )
    assert isinstance(out, str)
    assert "Selbstschutz" in out
    assert "GPU-Status: NVIDIA RTX 2060 SUPER, 8 GB" in out
