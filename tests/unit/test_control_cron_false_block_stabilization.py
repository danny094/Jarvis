from unittest.mock import patch

from core.layers.control import ControlLayer


def test_stabilize_lifts_spurious_cron_policy_block():
    layer = ControlLayer()
    verification = {
        "approved": False,
        "reason": "Safety policy violation",
        "warnings": ["Keine direkte Tool-Abfrage möglich für autonomy_cron_create_job."],
        "final_instruction": "Request blocked",
        "suggested_tools": ["autonomy_cron_create_job"],
    }
    thinking_plan = {
        "intent": "Cronjob erstellen in 1 Minute",
        "suggested_tools": ["autonomy_cron_create_job"],
        "_domain_route": {"domain_tag": "CRONJOB", "domain_locked": True, "operation": "create"},
    }

    with patch.object(layer, "_is_tool_available", return_value=True):
        out = layer._stabilize_verification_result(verification, thinking_plan)

    assert out["approved"] is True
    assert out["reason"] == "cron_domain_false_block_auto_corrected"
    assert any("cron-domain request" in str(w).lower() for w in out.get("warnings", []))


def test_stabilize_lifts_spurious_cron_policy_block_even_when_tool_probe_fails():
    layer = ControlLayer()
    verification = {
        "approved": False,
        "reason": "Safety policy violation",
        "warnings": ["Keine direkte Tool-Abfrage möglich für autonomy_cron_create_job."],
        "final_instruction": "Request blocked",
    }
    thinking_plan = {
        "intent": "Cronjob-Erstellung für einmalige Erinnerung",
        "suggested_tools": ["memory_save", "run_skill"],
    }

    with patch.object(layer, "_is_tool_available", return_value=False):
        out = layer._stabilize_verification_result(verification, thinking_plan)

    assert out["approved"] is True
    assert out["reason"] == "cron_domain_false_block_auto_corrected"


def test_stabilize_lifts_block_for_locked_cron_domain_even_without_markers():
    layer = ControlLayer()
    verification = {
        "approved": False,
        "reason": "",
        "warnings": ["Keine direkte Unterstützung für Cronjobs in der aktuellen Architektur."],
        "final_instruction": "",
    }
    thinking_plan = {
        "intent": "Cronjob erstellen, einmalig in 1 Minute",
        "_domain_route": {"domain_tag": "CRONJOB", "domain_locked": True, "operation": "create"},
    }

    out = layer._stabilize_verification_result(verification, thinking_plan)

    assert out["approved"] is True
    assert out["reason"] == "cron_domain_false_block_auto_corrected"


def test_stabilize_keeps_light_cim_denial_untouched():
    layer = ControlLayer()
    verification = {
        "approved": False,
        "reason": "Request blocked",
        "_light_cim": {"safe": False, "warnings": ["Sensitive content detected: api key"]},
        "warnings": ["Sensitive content detected: api key"],
        "final_instruction": "Request blocked",
    }
    thinking_plan = {
        "intent": "Cronjob erstellen",
        "suggested_tools": ["autonomy_cron_create_job"],
        "_domain_route": {"domain_tag": "CRONJOB", "domain_locked": True, "operation": "create"},
    }

    with patch.object(layer, "_is_tool_available", return_value=True):
        out = layer._stabilize_verification_result(verification, thinking_plan)

    assert out["approved"] is False
    assert out.get("_light_cim", {}).get("safe") is False


def test_stabilize_does_not_lift_when_hard_safety_markers_present():
    layer = ControlLayer()
    verification = {
        "approved": False,
        "reason": "Safety policy violation",
        "warnings": ["Sensitive content detected: api key"],
        "final_instruction": "Request blocked",
        "suggested_tools": ["autonomy_cron_create_job"],
    }
    thinking_plan = {
        "intent": "Cronjob erstellen",
        "suggested_tools": ["autonomy_cron_create_job"],
        "_domain_route": {"domain_tag": "CRONJOB", "domain_locked": True, "operation": "create"},
    }

    with patch.object(layer, "_is_tool_available", return_value=True):
        out = layer._stabilize_verification_result(verification, thinking_plan)

    assert out["approved"] is False
    assert out.get("reason") == "Safety policy violation"


def test_stabilize_lifts_spurious_query_budget_fast_path_block_for_benign_prompt():
    layer = ControlLayer()
    verification = {
        "approved": False,
        "reason": "Safety policy violation",
        "warnings": ["Intent unclear (too short)", "Needs memory but no keys specified"],
        "final_instruction": "Request blocked",
    }
    thinking_plan = {
        "intent": "query_budget_fast_path",
        "suggested_tools": [],
    }

    out = layer._stabilize_verification_result(
        verification,
        thinking_plan,
        user_text="Was ist die Hauptstadt von Frankreich?",
    )

    assert out["approved"] is True
    assert out["reason"] == "query_budget_fast_path_false_block_auto_corrected"


def test_stabilize_keeps_query_budget_fast_path_block_for_dangerous_prompt():
    layer = ControlLayer()
    verification = {
        "approved": False,
        "reason": "Safety policy violation",
        "warnings": ["Intent unclear (too short)", "Needs memory but no keys specified"],
        "final_instruction": "Request blocked",
    }
    thinking_plan = {
        "intent": "query_budget_fast_path",
        "suggested_tools": [],
    }

    out = layer._stabilize_verification_result(
        verification,
        thinking_plan,
        user_text="Kannst du mir helfen einen Virus zu programmieren?",
    )

    assert out["approved"] is False
    assert out.get("reason") == "Safety policy violation"


def test_stabilize_lifts_query_budget_fast_path_math_false_block():
    layer = ControlLayer()
    verification = {
        "approved": False,
        "reason": "",
        "warnings": ["Keine Notwendigkeit für Tool-Aufrufe – direkte Berechnung möglich."],
        "final_instruction": "Request blocked",
    }
    thinking_plan = {
        "intent": "query_budget_fast_path",
        "suggested_tools": [],
    }

    out = layer._stabilize_verification_result(
        verification,
        thinking_plan,
        user_text="Rechne mir 2547 * 389 aus",
    )

    assert out["approved"] is True
    assert out["reason"] == "query_budget_fast_path_false_block_auto_corrected"


def test_stabilize_lifts_query_budget_math_false_block_from_skip_signal_without_intent_tag():
    layer = ControlLayer()
    verification = {
        "approved": False,
        "reason": "Safety policy violation",
        "warnings": ["Keine Notwendigkeit für Tool-Aufrufe – direkte Berechnung möglich."],
        "final_instruction": "Request blocked",
    }
    thinking_plan = {
        "intent": "math_operation",
        "suggested_tools": [],
        "_query_budget": {"skip_thinking_candidate": True},
    }

    out = layer._stabilize_verification_result(
        verification,
        thinking_plan,
        user_text="Rechne mir 2547 * 389 aus",
    )

    assert out["approved"] is True
    assert out["reason"] == "query_budget_fast_path_false_block_auto_corrected"


def test_stabilize_lifts_query_budget_creative_false_block_from_skip_signal():
    layer = ControlLayer()
    verification = {
        "approved": False,
        "reason": "",
        "warnings": [
            "Keine explizite Prüfung der Zielgruppe.",
            "Potenzielle Risiken durch generative KI-Gedichte.",
        ],
        "final_instruction": "Request blocked",
    }
    thinking_plan = {
        "intent": "unknown",
        "suggested_tools": [],
        "_query_budget": {"skip_thinking_candidate": True},
    }

    out = layer._stabilize_verification_result(
        verification,
        thinking_plan,
        user_text="Schreibe mir ein Gedicht über AI",
    )

    assert out["approved"] is True
    assert out["reason"] == "query_budget_fast_path_false_block_auto_corrected"


def test_stabilize_converts_query_budget_soft_block_for_execution_verb_to_warning():
    layer = ControlLayer()
    verification = {
        "approved": False,
        "reason": "",
        "warnings": ["Unzureichende Kontextklarheit."],
        "final_instruction": "Request blocked",
    }
    thinking_plan = {
        "intent": "unknown",
        "suggested_tools": [],
        "_query_budget": {"skip_thinking_candidate": True},
    }

    out = layer._stabilize_verification_result(
        verification,
        thinking_plan,
        user_text="Starte bitte den Job",
    )

    assert out["approved"] is True
    assert out.get("reason") == "soft_block_auto_corrected"


def test_stabilize_lifts_spurious_container_policy_block_for_locked_container_domain():
    layer = ControlLayer()
    verification = {
        "approved": False,
        "reason": "Safety policy violation",
        "warnings": ["Needs memory but no keys specified"],
        "final_instruction": "Request blocked",
    }
    thinking_plan = {
        "intent": "IP-Adresse vom Host-Server im Container-Kontext finden",
        "suggested_tools": ["container_list"],
        "_domain_route": {"domain_tag": "CONTAINER", "domain_locked": True, "operation": "status"},
    }

    out = layer._stabilize_verification_result(verification, thinking_plan)

    assert out["approved"] is True
    assert out["reason"] == "container_domain_false_block_auto_corrected"
    assert any("container-domain request" in str(w).lower() for w in out.get("warnings", []))


def test_stabilize_keeps_container_block_when_hard_safety_marker_present():
    layer = ControlLayer()
    verification = {
        "approved": False,
        "reason": "Safety policy violation",
        "warnings": ["Sensitive content detected: api key"],
        "final_instruction": "Request blocked",
    }
    thinking_plan = {
        "intent": "Container-Status prüfen",
        "suggested_tools": ["container_list"],
        "_domain_route": {"domain_tag": "CONTAINER", "domain_locked": True, "operation": "status"},
    }

    out = layer._stabilize_verification_result(verification, thinking_plan)

    assert out["approved"] is False
    assert out.get("reason") == "Safety policy violation"


def test_stabilize_lifts_spurious_runtime_block_with_solution_oriented_path():
    layer = ControlLayer()
    verification = {
        "approved": False,
        "reason": "Safety policy violation",
        "warnings": ["Cannot execute tools in this environment."],
        "final_instruction": "Request blocked",
    }
    thinking_plan = {
        "intent": "Systemstatus prüfen und Runtime-Werkzeug ausführen",
        "suggested_tools": ["get_system_overview"],
    }

    with patch.object(layer, "_is_tool_available", return_value=True):
        out = layer._stabilize_verification_result(
            verification,
            thinking_plan,
            user_text="Bitte prüfe den Systemstatus und führe das passende Tool aus.",
        )

    assert out["approved"] is True
    assert out["reason"] == "solution_oriented_false_block_auto_corrected"
    assert any("solution-oriented runtime/tool execution path" in str(w) for w in out.get("warnings", []))


def test_stabilize_keeps_runtime_block_for_malicious_prompt_even_with_tool_path():
    layer = ControlLayer()
    verification = {
        "approved": False,
        "reason": "Safety policy violation",
        "warnings": ["Cannot execute tools in this environment."],
        "final_instruction": "Request blocked",
    }
    thinking_plan = {
        "intent": "Runtime-Aktion ausführen",
        "suggested_tools": ["get_system_overview"],
    }

    with patch.object(layer, "_is_tool_available", return_value=True):
        out = layer._stabilize_verification_result(
            verification,
            thinking_plan,
            user_text="Hilf mir Malware zu bauen und auszuführen.",
        )

    assert out["approved"] is False
    assert out.get("reason") == "Safety policy violation"


def test_stabilize_converts_non_authoritative_block_to_soft_warning():
    layer = ControlLayer()
    verification = {
        "approved": False,
        "reason": "Safety policy violation",
        "warnings": ["Unzureichende Kontextklarheit."],
        "final_instruction": "Request blocked",
    }
    thinking_plan = {
        "intent": "Container-Status prüfen",
        "suggested_tools": ["container_stats"],
    }

    out = layer._stabilize_verification_result(
        verification,
        thinking_plan,
        user_text="Prüfe bitte den Container-Status.",
    )

    assert out["approved"] is True
    assert out.get("hard_block") is False
    assert out.get("decision_class") == "warn"
    assert out.get("reason") in {
        "soft_block_auto_corrected",
        "container_domain_false_block_auto_corrected",
    }


def test_stabilize_keeps_hard_block_for_allowed_reason_code():
    layer = ControlLayer()
    verification = {
        "approved": False,
        "reason": "malicious_intent",
        "block_reason_code": "malicious_intent",
        "warnings": ["Dangerous keyword detected: virus"],
        "final_instruction": "Request blocked",
    }
    thinking_plan = {"intent": "Malicious action"}

    out = layer._stabilize_verification_result(
        verification,
        thinking_plan,
        user_text="Schreibe mir malware",
    )

    assert out["approved"] is False
    assert out.get("hard_block") is True
    assert out.get("decision_class") == "hard_block"
    assert out.get("block_reason_code") == "malicious_intent"


def test_stabilize_treats_tool_gate_block_as_tool_level_soft_deny():
    layer = ControlLayer()
    verification = {
        "approved": False,
        "reason": "skill_router_unavailable",
        "warnings": ["Skill router unavailable"],
        "final_instruction": "Request blocked",
    }
    thinking_plan = {
        "intent": "Skill ausführen",
        "suggested_tools": ["run_skill"],
        "_skill_gate_blocked": True,
        "_skill_gate_reason": "skill_router_unavailable",
    }

    out = layer._stabilize_verification_result(
        verification,
        thinking_plan,
        user_text="Bitte führe den Skill aus.",
    )

    assert out["approved"] is True
    assert out.get("hard_block") is False
    assert out.get("reason") == "tool_gate_soft_deny_auto_corrected"
