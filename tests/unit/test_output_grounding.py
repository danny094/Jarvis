import asyncio
import json
from unittest.mock import patch

from core.layers.output import OutputLayer
from core.plan_runtime_bridge import (
    get_runtime_grounding_value,
    set_runtime_carryover_grounding_evidence,
    set_runtime_grounding_evidence,
    set_runtime_tool_results,
)


def _grounding(plan, key: str, default=None):
    return get_runtime_grounding_value(plan, key=key, default=default)


def _policy():
    return {
        "output": {
            "enforce_evidence_for_fact_query": True,
            "enforce_evidence_when_tools_used": True,
            "enforce_evidence_when_tools_suggested": True,
            "min_successful_evidence": 1,
            "allowed_evidence_statuses": ["ok"],
            "fact_query_response_mode": "model",
            "fallback_mode": "explicit_uncertainty",
            "forbid_new_numeric_claims": True,
            "forbid_unverified_qualitative_claims": True,
            "qualitative_claim_guard": {
                "min_token_length": 5,
                "max_overall_novelty_ratio": 0.72,
                "max_sentence_novelty_ratio": 0.82,
                "min_sentence_tokens": 4,
                "min_assertive_sentence_violations": 1,
                "assertive_cues": ["is", "runs", "uses", "ist", "läuft", "nutzt"],
                "ignored_tokens": ["system", "model", "modell"],
            },
        }
    }


def test_grounding_precheck_missing_evidence_uses_fallback_mode_without_hard_block():
    layer = OutputLayer()
    plan = {
        "is_fact_query": True,
        "suggested_tools": ["get_system_info"],
    }
    set_runtime_grounding_evidence(plan, [])
    with patch("core.layers.output.load_grounding_policy", return_value=_policy()):
        precheck = layer._grounding_precheck(plan, memory_data="")
    assert precheck["blocked"] is False
    assert precheck.get("mode") == "missing_evidence_fallback"
    assert _grounding(plan, "missing_evidence", False) is True
    assert "keinen verifizierten tool-nachweis" in precheck["response"].lower()


def test_grounding_precheck_conversational_mode_does_not_require_evidence_for_suggested_tools():
    layer = OutputLayer()
    plan = {
        "dialogue_act": "smalltalk",
        "conversation_mode": "conversational",
        "suggested_tools": ["request_container"],
    }
    set_runtime_grounding_evidence(plan, [])
    with patch("core.layers.output.load_grounding_policy", return_value=_policy()):
        precheck = layer._grounding_precheck(plan, memory_data="")
    assert precheck["blocked"] is False
    assert precheck.get("mode") == "pass"
    assert _grounding(plan, "missing_evidence", False) is False


def test_grounding_precheck_tool_error_uses_fallback_mode_without_hard_block():
    layer = OutputLayer()
    plan = {"is_fact_query": False}
    set_runtime_tool_results(plan, "[TOOL-CARD: autonomy_cron_create_job | ❌ error | ref:abc]")
    set_runtime_grounding_evidence(plan, [
        {
            "tool_name": "autonomy_cron_create_job",
            "status": "error",
            "key_facts": ["cron interval 60s is below policy minimum 300s"],
        }
    ])
    with patch("core.layers.output.load_grounding_policy", return_value=_policy()):
        precheck = layer._grounding_precheck(plan, memory_data="")
    assert precheck["blocked"] is False
    assert precheck.get("blocked_reason") == "tool_execution_failed"
    assert precheck.get("mode") == "tool_execution_failed_fallback"
    assert _grounding(plan, "tool_execution_failed", False) is True
    assert "autonomy_cron_create_job" in precheck["response"]
    assert "60s" in precheck["response"]
    assert "keinen verifizierten tool-nachweis" not in precheck["response"].lower()


def test_grounding_precheck_needs_clarification_passes_through():
    layer = OutputLayer()
    plan = {
        "is_fact_query": False,
        "suggested_tools": ["request_container"],
        "conversation_mode": "task",
    }
    set_runtime_grounding_evidence(
        plan,
        [
            {
                "tool_name": "request_container",
                "status": "needs_clarification",
                "reason": "Mehrere Blueprints passen; bitte Nutzer fragen",
                "key_facts": [],
            }
        ],
    )
    with patch("core.layers.output.load_grounding_policy", return_value=_policy()):
        precheck = layer._grounding_precheck(plan, memory_data="")
    assert precheck["blocked"] is False
    assert precheck.get("mode") == "pass"
    assert precheck.get("blocked_reason") == "needs_clarification"
    assert precheck.get("response") == ""
    assert _grounding(plan, "missing_evidence", False) is False


def test_stream_postcheck_mode_defaults_to_tail_repair():
    layer = OutputLayer()
    mode = layer._resolve_stream_postcheck_mode({})
    assert mode == "tail_repair"


def test_stream_postcheck_enabled_respects_off_mode():
    layer = OutputLayer()
    precheck = {
        "policy": {
            "stream_postcheck_mode": "off",
            "forbid_new_numeric_claims": True,
            "forbid_unverified_qualitative_claims": True,
        },
        "is_fact_query": True,
    }
    assert layer._stream_postcheck_enabled(precheck) is False


def test_skill_catalog_context_forces_buffered_stream_postcheck_in_tail_repair_mode():
    layer = OutputLayer()
    plan = {
        "resolution_strategy": "skill_catalog_context",
        "_skill_catalog_context": {"installed_count": 0, "draft_count": 1},
    }
    assert layer._should_buffer_stream_postcheck(
        plan,
        {
            "stream_postcheck_mode": "tail_repair",
            "forbid_new_numeric_claims": True,
            "forbid_unverified_qualitative_claims": True,
        },
        postcheck_enabled=True,
    ) is True


def test_container_contract_forces_buffered_stream_postcheck_in_tail_repair_mode():
    layer = OutputLayer()
    plan = {
        "_container_query_policy": {
            "query_class": "container_inventory",
            "required_tools": ["container_list"],
            "truth_mode": "runtime_inventory",
        }
    }
    assert layer._should_buffer_stream_postcheck(
        plan,
        {
            "stream_postcheck_mode": "tail_repair",
            "forbid_new_numeric_claims": True,
            "forbid_unverified_qualitative_claims": True,
        },
        postcheck_enabled=True,
    ) is True


def test_non_skill_catalog_tail_repair_stays_unbuffered():
    layer = OutputLayer()
    plan = {
        "is_fact_query": True,
        "suggested_tools": ["get_system_info"],
    }
    assert layer._should_buffer_stream_postcheck(
        plan,
        {
            "stream_postcheck_mode": "tail_repair",
            "forbid_new_numeric_claims": True,
            "forbid_unverified_qualitative_claims": True,
        },
        postcheck_enabled=True,
    ) is False


def test_task_loop_step_runtime_stays_unbuffered_even_with_analysis_guard():
    layer = OutputLayer()
    plan = {
        "intent": "Pruefe kurz den neuen Multistep Loop und zeige sichere Zwischenstaende",
        "needs_sequential_thinking": True,
        "_loop_trace_mode": "internal_loop_analysis",
        "_task_loop_step_runtime": True,
        "is_fact_query": False,
    }
    assert layer._should_buffer_stream_postcheck(
        plan,
        {
            "stream_postcheck_mode": "tail_repair",
            "forbid_new_numeric_claims": True,
            "forbid_unverified_qualitative_claims": True,
        },
        postcheck_enabled=True,
    ) is False


def test_analysis_turn_prompt_includes_guard_rules():
    layer = OutputLayer()
    plan = {
        "intent": "Pruefe kurz den neuen Multistep Loop und zeige sichere Zwischenstaende",
        "needs_sequential_thinking": True,
        "is_fact_query": False,
    }
    with patch("core.layers.output.load_grounding_policy", return_value=_policy()):
        prompt = layer.build_system_prompt(plan, memory_data="")
    assert "### ANALYSE-GUARD:" in prompt
    assert "konzeptionelle Analyse ohne Runtime-Nachweise" in prompt
    assert "Erfinde keine abgeschlossenen Checks" in prompt


def test_stream_postcheck_enabled_for_analysis_turn_guard():
    layer = OutputLayer()
    plan = {
        "intent": "Pruefe kurz den neuen Multistep Loop",
        "needs_sequential_thinking": True,
        "is_fact_query": False,
    }
    precheck = {
        "policy": _policy()["output"],
        "is_fact_query": False,
        "has_tool_usage": False,
        "verified_plan": plan,
    }
    assert layer._stream_postcheck_enabled(precheck) is True


def test_stream_postcheck_enabled_for_internal_loop_trace_guard_without_sequential_flag():
    layer = OutputLayer()
    plan = {
        "intent": "Pruefe kurz den neuen Multistep Loop",
        "_loop_trace_mode": "internal_loop_analysis",
        "is_fact_query": False,
    }
    precheck = {
        "policy": _policy()["output"],
        "is_fact_query": False,
        "has_tool_usage": False,
        "verified_plan": plan,
    }
    assert layer._stream_postcheck_enabled(precheck) is True


def test_output_budget_caps_interactive_analytical_query():
    layer = OutputLayer()
    plan = {
        "_response_mode": "interactive",
        "response_length_hint": "medium",
        "_query_budget": {"query_type": "analytical"},
    }
    with patch("core.layers.output.get_output_char_cap_interactive", return_value=2600), \
         patch("core.layers.output.get_output_char_target_interactive", return_value=1600), \
         patch("core.layers.output.get_output_char_cap_interactive_analytical", return_value=1400), \
         patch("core.layers.output.get_output_char_target_interactive_analytical", return_value=1000):
        budgets = layer._resolve_output_budgets(plan)
    assert budgets["hard_cap"] == 1400
    assert budgets["soft_target"] <= 1000


def test_grounding_postcheck_fallback_on_unknown_numeric_claim():
    layer = OutputLayer()
    plan = {}
    precheck = {
        "policy": {"forbid_new_numeric_claims": True, "fallback_mode": "explicit_uncertainty"},
        "evidence": [
            {
                "tool_name": "get_system_info",
                "status": "ok",
                "key_facts": ["NVIDIA GeForce RTX 2060 SUPER, 8 GB VRAM"],
            }
        ],
        "is_fact_query": True,
    }
    answer = "System läuft auf RTX 2060 SUPER mit 8 GB VRAM und eignet sich für 70B Modelle."
    checked = layer._grounding_postcheck(answer, plan, precheck)
    assert checked != answer
    assert _grounding(plan, "violation_detected", False) is True
    assert "70b" not in checked.lower()


def test_grounding_postcheck_keeps_answer_when_numeric_claims_are_supported():
    layer = OutputLayer()
    plan = {}
    precheck = {
        "policy": {"forbid_new_numeric_claims": True, "fallback_mode": "explicit_uncertainty"},
        "evidence": [
            {
                "tool_name": "get_system_info",
                "status": "ok",
                "key_facts": ["NVIDIA GeForce RTX 2060 SUPER, 8 GB VRAM"],
            }
        ],
        "is_fact_query": True,
    }
    answer = "System läuft auf RTX 2060 SUPER mit 8 GB VRAM."
    checked = layer._grounding_postcheck(answer, plan, precheck)
    assert checked == answer


def test_analysis_turn_postcheck_repairs_memory_and_runtime_drift():
    layer = OutputLayer()
    plan = {
        "intent": "Pruefe kurz den neuen Multistep Loop und zeige sichere Zwischenstaende",
        "needs_sequential_thinking": True,
        "is_fact_query": False,
    }
    layer._set_runtime_grounding_value(
        plan,
        None,
        "analysis_guard_user_text",
        "Pruefe kurz den neuen Multistep Loop und zeige sichere Zwischenstaende",
    )
    layer._set_runtime_grounding_value(
        plan,
        None,
        "analysis_guard_memory_present",
        False,
    )
    precheck = {
        "policy": _policy()["output"],
        "evidence": [],
        "is_fact_query": False,
        "has_tool_usage": False,
        "verified_plan": plan,
    }
    answer = (
        "Hier ist ein sicherer Zwischenstand basierend auf den Fakten aus deinem Gedaechtnis. "
        "VRAM und RAM sind im gruenen Bereich."
    )
    checked = layer._grounding_postcheck(answer, plan, precheck)
    assert checked.startswith("Sicherer Zwischenstand:")
    assert "ohne ausgefuehrte Tools oder Runtime-Checks" in checked
    assert _grounding(plan, "repair_used", False) is True
    violation = _grounding(plan, "analysis_guard_violation", {})
    assert "unsupported_memory_claim" in violation.get("reasons", [])
    assert "runtime_resources" in violation.get("reasons", [])
    assert "runtime_health" in violation.get("reasons", [])


def test_analysis_turn_postcheck_repairs_fabricated_completion_claims():
    layer = OutputLayer()
    plan = {
        "intent": "Pruefe kurz den neuen Multistep Loop und zeige sichere Zwischenstaende",
        "needs_sequential_thinking": True,
        "is_fact_query": False,
    }
    layer._set_runtime_grounding_value(
        plan,
        None,
        "analysis_guard_user_text",
        "Pruefe kurz den neuen Multistep Loop und zeige sichere Zwischenstaende",
    )
    precheck = {
        "policy": _policy()["output"],
        "evidence": [],
        "is_fact_query": False,
        "has_tool_usage": False,
        "verified_plan": plan,
    }
    answer = (
        "1. Schritt 1 erledigt.\n"
        "2. Schritt 2 abgeschlossen.\n"
        "Systemcheck im gruenen Bereich."
    )
    checked = layer._grounding_postcheck(answer, plan, precheck)
    assert checked.startswith("Sicherer Zwischenstand:")
    violation = _grounding(plan, "analysis_guard_violation", {})
    assert "fabricated_completion_claim" in violation.get("reasons", [])
    assert _grounding(plan, "violation_detected", False) is True


def test_analysis_turn_postcheck_repairs_internal_loop_trace_prompt_without_sequential_flag():
    layer = OutputLayer()
    plan = {
        "intent": "Pruefe kurz den neuen Multistep Loop und zeige sichere Zwischenstaende",
        "_loop_trace_mode": "internal_loop_analysis",
        "is_fact_query": False,
    }
    layer._set_runtime_grounding_value(
        plan,
        None,
        "analysis_guard_user_text",
        "Pruefe kurz den neuen Multistep Loop und zeige sichere Zwischenstaende",
    )
    precheck = {
        "policy": _policy()["output"],
        "evidence": [],
        "is_fact_query": False,
        "has_tool_usage": False,
        "verified_plan": plan,
    }
    answer = "Systemcheck im gruenen Bereich. Schritt 1 abgeschlossen."
    checked = layer._grounding_postcheck(answer, plan, precheck)
    assert checked.startswith("Sicherer Zwischenstand:")
    assert _grounding(plan, "repair_used", False) is True
    evaluation = _grounding(plan, "analysis_guard_evaluation", {})
    assert evaluation.get("applicable") is True
    assert evaluation.get("trigger_source") == "loop_trace_mode"
    violation = _grounding(plan, "analysis_guard_violation", {})
    assert "runtime_health" in violation.get("reasons", [])
    assert "fabricated_completion_claim" in violation.get("reasons", [])


def test_analysis_turn_postcheck_records_guard_evaluation_for_clean_internal_loop_trace_prompt():
    layer = OutputLayer()
    plan = {
        "intent": "Pruefe kurz den neuen Multistep Loop und zeige sichere Zwischenstaende",
        "_loop_trace_mode": "internal_loop_analysis",
        "is_fact_query": False,
    }
    layer._set_runtime_grounding_value(
        plan,
        None,
        "analysis_guard_user_text",
        "Pruefe kurz den neuen Multistep Loop und zeige sichere Zwischenstaende",
    )
    precheck = {
        "policy": _policy()["output"],
        "evidence": [],
        "is_fact_query": False,
        "has_tool_usage": False,
        "verified_plan": plan,
    }
    answer = "Sicherer Zwischenstand: Ich kann den naechsten Schritt konzeptionell ableiten."
    checked = layer._grounding_postcheck(answer, plan, precheck)
    assert checked == answer
    evaluation = _grounding(plan, "analysis_guard_evaluation", {})
    assert evaluation.get("applicable") is True
    assert evaluation.get("trigger_source") == "loop_trace_mode"
    assert evaluation.get("violated") is False
    assert int(evaluation.get("checked_chars") or 0) == len(answer)


def test_container_inventory_postcheck_repair_uses_structured_container_fallback():
    layer = OutputLayer()
    plan = {
        "_container_query_policy": {
            "query_class": "container_inventory",
            "required_tools": ["container_list"],
            "truth_mode": "runtime_inventory",
        }
    }
    precheck = {
        "policy": {"forbid_new_numeric_claims": True, "fallback_mode": "explicit_uncertainty"},
        "evidence": [
            {
                "tool_name": "container_list",
                "status": "ok",
                "key_facts": [
                    "trion-managed container count: 3",
                    "running containers: none",
                    "stopped containers: trion-home, runtime-hardware, filestash",
                ],
                "structured": {
                    "containers": [
                        {"blueprint_id": "trion-home", "state": "exited"},
                        {"blueprint_id": "runtime-hardware", "state": "exited"},
                        {"blueprint_id": "filestash", "state": "exited"},
                    ]
                },
            }
        ],
        "is_fact_query": True,
    }
    answer = "Laufende Container: keine. Gestoppte Container: trion-home, runtime-hardware, filestash. Das sind 12 Eintraege und Exit 137 ist kritisch."
    checked = layer._grounding_postcheck(answer, plan, precheck)
    assert checked.startswith("Laufende Container:")
    assert "Gestoppte Container: trion-home, runtime-hardware, filestash." in checked
    assert "Verifizierte Ergebnisse:" not in checked


def test_container_state_binding_postcheck_repair_uses_container_inspect_fallback():
    layer = OutputLayer()
    plan = {
        "_container_query_policy": {
            "query_class": "container_state_binding",
            "required_tools": ["container_inspect", "container_list"],
            "truth_mode": "session_binding",
        }
    }
    precheck = {
        "policy": {"forbid_new_numeric_claims": True, "fallback_mode": "explicit_uncertainty"},
        "evidence": [
            {
                "tool_name": "container_inspect",
                "status": "ok",
                "structured": {
                    "container_id": "ctr-home",
                    "name": "trion-home",
                    "blueprint_id": "trion-home",
                    "status": "running",
                    "running": True,
                },
            }
        ],
        "is_fact_query": True,
    }
    answer = "Aktiver Container: unklar. Wenn du willst, starte ich den Container neu."
    checked = layer._grounding_postcheck(answer, plan, precheck)
    assert checked.startswith("Aktiver Container: trion-home.")
    assert "Runtime-Status des aktiven Ziels trion-home: running." in checked


def test_container_state_binding_postcheck_repairs_time_and_profile_leakage():
    layer = OutputLayer()
    plan = {
        "_container_query_policy": {
            "query_class": "container_state_binding",
            "required_tools": ["container_inspect", "container_list"],
            "truth_mode": "session_binding",
        }
    }
    precheck = {
        "policy": {"forbid_new_numeric_claims": True, "fallback_mode": "explicit_uncertainty"},
        "evidence": [
            {
                "tool_name": "container_list",
                "status": "ok",
                "structured": {
                    "containers": [
                        {
                            "container_id": "ctr-home",
                            "name": "trion_trion-home_1775069490675_6d5867",
                            "blueprint_id": "trion-home",
                            "status": "running",
                        }
                    ]
                },
            }
        ],
        "is_fact_query": True,
    }
    answer = (
        "Aktiver Container: trion_trion-home_1775069490675_6d5867.\n"
        "Binding/Status: Laeuft seit 2026-04-01T18:51:30.688781 (vor etwa 6 Tagen).\n"
        "Einordnung: Alpine-basierte Shell-Umgebung mit Systemtools (Blueprint: shell-sandbox)"
    )
    checked = layer._grounding_postcheck(answer, plan, precheck)
    assert checked == (
        "Aktiver Container: nicht verifiziert.\n"
        "Binding/Status: Laufende TRION-managed Container: trion-home.\n"
        "Einordnung: Binding, Runtime-Inventar und Blueprint-Katalog bleiben getrennt."
    )


def test_container_blueprint_postcheck_blocks_runtime_leakage_without_inventory_evidence():
    layer = OutputLayer()
    plan = {
        "_container_query_policy": {
            "query_class": "container_blueprint_catalog",
            "required_tools": ["blueprint_list"],
            "truth_mode": "blueprint_catalog",
        }
    }
    precheck = {
        "policy": {
            "forbid_new_numeric_claims": True,
            "forbid_unverified_qualitative_claims": True,
            "fallback_mode": "explicit_uncertainty",
        },
        "evidence": [
            {
                "tool_name": "blueprint_list",
                "status": "ok",
                "key_facts": [
                    "blueprint count: 4",
                    "available blueprints: db-sandbox, node-sandbox, python-sandbox, shell-sandbox",
                ],
                "structured": {
                    "blueprints": [
                        {"id": "db-sandbox", "name": "Database Sandbox"},
                        {"id": "node-sandbox", "name": "Node.js Sandbox"},
                        {"id": "python-sandbox", "name": "Python Sandbox"},
                        {"id": "shell-sandbox", "name": "Shell Sandbox"},
                    ]
                },
            }
        ],
        "is_fact_query": True,
    }
    answer = "Verfuegbare Blueprints: Database Sandbox, Node.js Sandbox, Python Sandbox, Shell Sandbox. Aktueller Status: Keine laufenden Container."
    checked = layer._grounding_postcheck(answer, plan, precheck)
    assert checked.startswith("Verfuegbare Blueprints:")
    assert "Keine laufenden Container" not in checked
    assert "Blueprint-Katalog-Befund" in checked


def test_grounding_precheck_strict_fact_mode_returns_evidence_summary():
    layer = OutputLayer()
    plan = {"is_fact_query": True}
    set_runtime_tool_results(plan, "[TOOL-CARD: get_system_info | ✅ ok | ref:abc]")
    set_runtime_grounding_evidence(plan, [
        {
            "tool_name": "get_system_info",
            "status": "ok",
            "structured": {
                "output": "GPU: NVIDIA GeForce RTX 2060 SUPER\nVRAM total: 8192 MiB\nVRAM frei: 792 MiB"
            },
            "key_facts": [],
        }
    ])
    policy = _policy()
    policy["output"]["fact_query_response_mode"] = "evidence_summary"
    with patch("core.layers.output.load_grounding_policy", return_value=policy):
        precheck = layer._grounding_precheck(plan, memory_data="")
    assert precheck["blocked"] is False
    assert precheck.get("mode") == "evidence_summary_fallback"
    assert "Verifizierte Ergebnisse" in precheck["response"]
    assert "NVIDIA GeForce RTX 2060 SUPER" in precheck["response"]


def test_grounding_postcheck_fallback_on_unverified_qualitative_claim():
    layer = OutputLayer()
    plan = {}
    precheck = {
        "policy": _policy()["output"],
        "evidence": [
            {
                "tool_name": "run_skill",
                "status": "ok",
                "key_facts": [
                    "--- TRION Hardware-Report ---",
                    "GPU: NVIDIA GeForce RTX 2060 SUPER",
                    "VRAM: 8.0 GB gesamt",
                ],
            }
        ],
        "is_fact_query": True,
    }
    answer = (
        "Das System läuft in einer Cloud-Infrastruktur von Mistral AI "
        "und nutzt virtualisierte Ressourcen."
    )
    checked = layer._grounding_postcheck(answer, plan, precheck)
    assert checked != answer
    assert _grounding(plan, "violation_detected", False) is True
    qv = _grounding(plan, "qualitative_violation", {})
    assert qv.get("violated") is True


def test_grounding_postcheck_keeps_supported_qualitative_claim():
    layer = OutputLayer()
    plan = {}
    precheck = {
        "policy": _policy()["output"],
        "evidence": [
            {
                "tool_name": "run_skill",
                "status": "ok",
                "key_facts": [
                    "GPU: NVIDIA GeForce RTX 2060 SUPER",
                    "VRAM: 8.0 GB gesamt",
                ],
            }
        ],
        "is_fact_query": True,
    }
    answer = "Das System läuft auf einer NVIDIA GeForce RTX 2060 SUPER mit 8.0 GB VRAM."
    checked = layer._grounding_postcheck(answer, plan, precheck)
    assert checked == answer
    assert _grounding(plan, "violation_detected", False) is not True


def test_generate_stream_uses_direct_response_short_circuit():
    layer = OutputLayer()
    plan = {"_execution_result": {"direct_response": "Cronjob erstellt: `cron-test`."}}

    async def _collect():
        chunks = []
        async for chunk in layer.generate_stream(
            user_text="dummy",
            verified_plan=plan,
            memory_data="",
            model="dummy-model",
        ):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(_collect())
    assert "".join(chunks) == "Cronjob erstellt: `cron-test`."


def test_generate_stream_skill_catalog_context_repair_does_not_leak_grounding_label():
    layer = OutputLayer()
    plan = {
        "is_fact_query": True,
        "resolution_strategy": "skill_catalog_context",
        "_skill_catalog_context": {"installed_count": 0, "draft_count": 1},
    }
    precheck = {
        "policy": {
            "stream_postcheck_mode": "tail_repair",
            "forbid_new_numeric_claims": True,
            "forbid_unverified_qualitative_claims": True,
        },
        "is_fact_query": True,
        "mode": "pass",
    }

    async def _fake_stream_chat(**_kwargs):
        yield "Ich habe viele Faehigkeiten."

    async def _collect():
        chunks = []
        with patch.object(layer, "_grounding_precheck", return_value=precheck), \
             patch.object(
                 layer,
                 "_grounding_postcheck",
                 return_value=(
                     "Runtime-Skills: Im Runtime-Skill-System sind aktuell keine "
                     "installierten Skills vorhanden.\n"
                     "Einordnung: Built-in Tools sind davon getrennt."
                 ),
             ), \
             patch("core.layers.output.resolve_role_provider", return_value="ollama"), \
             patch(
                 "core.layers.output.resolve_role_endpoint",
                 return_value={
                     "requested_target": "local",
                     "effective_target": "local",
                     "fallback_reason": "",
                     "endpoint_source": "test",
                     "hard_error": False,
                     "endpoint": "http://example.invalid",
                 },
             ), \
             patch("core.layers.output.stream_chat", new=_fake_stream_chat):
            async for chunk in layer.generate_stream(
                user_text="Welche Skills hast du?",
                verified_plan=plan,
                memory_data="",
                model="dummy-model",
            ):
                chunks.append(chunk)
        return chunks

    chunks = asyncio.run(_collect())
    merged = "".join(chunks)
    assert "[Grounding-Korrektur]" not in merged
    assert merged.startswith("Runtime-Skills:")


def test_generate_stream_non_skill_tail_repair_keeps_visible_grounding_label():
    layer = OutputLayer()
    plan = {
        "is_fact_query": True,
        "suggested_tools": ["get_system_info"],
    }
    precheck = {
        "policy": {
            "stream_postcheck_mode": "tail_repair",
            "forbid_new_numeric_claims": True,
            "forbid_unverified_qualitative_claims": True,
        },
        "is_fact_query": True,
        "mode": "pass",
    }

    async def _fake_stream_chat(**_kwargs):
        yield "Das System eignet sich fuer 70B."

    async def _collect():
        chunks = []
        with patch.object(layer, "_grounding_precheck", return_value=precheck), \
             patch.object(layer, "_grounding_postcheck", return_value="Verifizierte Korrektur."), \
             patch("core.layers.output.resolve_role_provider", return_value="ollama"), \
             patch(
                 "core.layers.output.resolve_role_endpoint",
                 return_value={
                     "requested_target": "local",
                     "effective_target": "local",
                     "fallback_reason": "",
                     "endpoint_source": "test",
                     "hard_error": False,
                     "endpoint": "http://example.invalid",
                 },
             ), \
             patch("core.layers.output.stream_chat", new=_fake_stream_chat):
            async for chunk in layer.generate_stream(
                user_text="Taugt das fuer 70B?",
                verified_plan=plan,
                memory_data="",
                model="dummy-model",
            ):
                chunks.append(chunk)
        return chunks

    chunks = asyncio.run(_collect())
    merged = "".join(chunks)
    assert "[Grounding-Korrektur]" in merged
    assert merged.endswith("Verifizierte Korrektur.")


# ---------------------------------------------------------------------------
# Tests für die Fixes: run_skill result-Extraktion + vollständige Evidence
# ---------------------------------------------------------------------------

_HARDWARE_REPORT = (
    "--- TRION Hardware-Report ---\n"
    "CPU: Unbekannte CPU (12 Threads) | Auslastung: 0.5%\n"
    "RAM: 31.19 GB gesamt | Genutzt: 9.69 GB\n"
    "GPU: NVIDIA GeForce RTX 2060 SUPER | VRAM: 8.0 GB gesamt, 0.77 GB frei, 7.23 GB genutzt | Auslastung: 68.0% | Temp: 57.0°C\n"
    "Speicher: 45.59 GB frei von 97.87 GB\n"
    "----------------------------"
)

_SKILL_RAW_RESULT = json.dumps({
    "success": True,
    "result": _HARDWARE_REPORT,
    "error": None,
    "execution_time_ms": 521.3,
    "sandbox_violations": [],
})


def test_grounding_evidence_entry_extracts_skill_result_lines():
    """_build_grounding_evidence_entry muss bei JSON mit 'result'-Key die Zeilen
    aus dem result-Text als key_facts verwenden — nicht die ersten 3 Zeilen des
    rohen JSON-Strings. GPU (Zeile 4) muss in key_facts landen."""
    from core.orchestrator import PipelineOrchestrator

    entry = PipelineOrchestrator._build_grounding_evidence_entry(
        tool_name="run_skill",
        raw_result=_SKILL_RAW_RESULT,
        status="ok",
        ref_id="test-fix-001",
    )

    facts = entry["key_facts"]
    gpu_in_facts = any("GPU" in f or "NVIDIA" in f or "GeForce" in f for f in facts)
    assert gpu_in_facts, f"GPU-Zeile fehlt in key_facts (nur {len(facts)} Einträge): {facts}"

    # 'result' muss in structured landen (für _build_grounding_fallback)
    structured = entry.get("structured", {})
    assert "result" in structured, f"'result' fehlt in structured: {structured.keys()}"
    assert "NVIDIA" in structured["result"]


def test_grounding_fallback_uses_result_field_not_raw_json():
    """_build_grounding_fallback muss bei structured.result (run_skill-Format)
    formatierten Text ausgeben, nicht den rohen JSON-String."""
    layer = OutputLayer()
    evidence = [
        {
            "tool_name": "run_skill",
            "status": "ok",
            "key_facts": [],
            "structured": {
                "success": True,
                "result": _HARDWARE_REPORT,
            },
        }
    ]

    fallback = layer._build_grounding_fallback(evidence, mode="explicit_uncertainty")

    assert '{"success":' not in fallback, "Fallback enthält rohen JSON-String"
    assert "TRION Hardware-Report" in fallback or "CPU" in fallback or "RAM" in fallback, (
        f"Fallback enthält keinen formatierten Hardware-Text: {fallback!r}"
    )


def test_grounding_fallback_keeps_gpu_line_for_hardware_reports():
    layer = OutputLayer()
    evidence = [
        {
            "tool_name": "run_skill",
            "status": "ok",
            "key_facts": [],
            "structured": {
                "success": True,
                "result": _HARDWARE_REPORT,
            },
        }
    ]

    fallback = layer._build_grounding_fallback(evidence, mode="explicit_uncertainty")
    assert "GPU:" in fallback or "GeForce" in fallback, fallback
    assert "VRAM" in fallback, fallback


def test_grounding_fallback_keeps_gpu_line_when_only_key_facts_available():
    layer = OutputLayer()
    evidence = [
        {
            "tool_name": "run_skill",
            "status": "ok",
            "key_facts": [
                "--- TRION Hardware-Report ---",
                "CPU: Unbekannte CPU (12 Threads) | Auslastung: 8.7%",
                "RAM: 31.19 GB gesamt | Genutzt: 7.2 GB",
                "GPU: NVIDIA GeForce RTX 2060 SUPER | VRAM: 8.0 GB gesamt, 3.22 GB frei, 4.78 GB genutzt | Auslastung: 34.0% | Temp: 55.0°C",
                "Speicher: 39.54 GB frei von 97.87 GB",
            ],
        }
    ]

    fallback = layer._build_grounding_fallback(evidence, mode="explicit_uncertainty")
    assert "GPU:" in fallback or "GeForce" in fallback, fallback
    assert "VRAM" in fallback, fallback


def test_grounding_postcheck_passes_for_full_hardware_answer():
    """Qualitative Guard darf NICHT feuern wenn die Antwort alle Hardware-
    Komponenten (CPU, RAM, GPU, Speicher) korrekt aus dem Tool-Ergebnis wiedergibt.
    Regression: früher fehlte GPU (Zeile 4) in der Evidence wegen [:3]-Limit."""
    layer = OutputLayer()
    plan = {}
    precheck = {
        "policy": _policy()["output"],
        "evidence": [
            {
                "tool_name": "run_skill",
                "status": "ok",
                "key_facts": [
                    "--- TRION Hardware-Report ---",
                    "CPU: Unbekannte CPU (12 Threads) | Auslastung: 0.5%",
                    "RAM: 31.19 GB gesamt | Genutzt: 9.69 GB",
                    "GPU: NVIDIA GeForce RTX 2060 SUPER | VRAM: 8.0 GB gesamt, 0.77 GB frei, 7.23 GB genutzt | Auslastung: 68.0% | Temp: 57.0°C",
                    "Speicher: 45.59 GB frei von 97.87 GB",
                ],
            }
        ],
        "is_fact_query": True,
    }
    # Zahlen müssen exakt mit Evidence übereinstimmen (68.0% nicht 68% —
    # numerische Normalisierung ist ein separates pre-existing Issue).
    answer = (
        "Hier sind die Hardware-Details des Systems:\n"
        "CPU: Unbekannte CPU mit 12 Threads, Auslastung 0.5%.\n"
        "RAM: 31.19 GB gesamt, davon 9.69 GB genutzt.\n"
        "GPU: NVIDIA GeForce RTX 2060 SUPER, VRAM 8.0 GB gesamt, 7.23 GB genutzt, Auslastung 68.0%.\n"
        "Speicher: 45.59 GB frei von 97.87 GB."
    )

    checked = layer._grounding_postcheck(answer, plan, precheck)

    assert checked == answer, (
        f"Guard hat fälschlich gefeuert. "
        f"violation={plan.get('_grounding_qualitative_violation')}"
    )
    assert _grounding(plan, "violation_detected", False) is not True


# ---------------------------------------------------------------------------
# Fix 3: Strict-Mode Tests — leerer Evidence-Blob
# ---------------------------------------------------------------------------

def _policy_no_numeric():
    """Policy ohne numerischen Guard — damit nur der qualitative Guard getestet wird."""
    p = _policy()["output"].copy()
    p["forbid_new_numeric_claims"] = False
    return p


def test_grounding_strict_mode_fires_when_evidence_empty_blob():
    """evidence vorhanden, aber kein extractable content (kein key_facts/structured) →
    strict mode → Guard feuert auch ohne sentence_violations (min wird auf 0 gesetzt)."""
    layer = OutputLayer()
    plan = {}
    # memory_graph_search-ähnliches Ergebnis: kein key_facts, kein structured
    precheck = {
        "policy": _policy_no_numeric(),
        "evidence": [
            {
                "tool_name": "memory_graph_search",
                "status": "ok",
                # Absichtlich kein key_facts, kein structured, kein metrics
            }
        ],
        "is_fact_query": True,
    }
    # Antwort ohne assertive_cues-Keywords (is/runs/uses/ist/läuft/nutzt) →
    # sentence_violations=0 mit normalem Guard → würde NICHT feuern
    # Im strict mode muss es trotzdem feuern
    answer = (
        "Das System habe keine Verbindung zur externen Cloud. "
        "Alle Daten wurden lokal archiviert worden. "
        "Keine externen Abhängigkeiten waren vorhanden."
    )
    checked = layer._grounding_postcheck(answer, plan, precheck)

    assert checked != answer, (
        "Strict-Mode muss feuern wenn evidence vorhanden aber leer (kein extractable content)"
    )
    assert _grounding(plan, "violation_detected", False) is True


def test_grounding_strict_mode_no_sentence_violations_needed():
    """Im strict mode reicht overall_ratio > 0.5 aus — sentence_violations=0 genügt."""
    layer = OutputLayer()
    plan = {}
    precheck = {
        "policy": _policy_no_numeric(),
        "evidence": [
            {
                "tool_name": "memory_graph_search",
                "status": "ok",
                # Kein key_facts / structured → leerer Evidence-Blob
            }
        ],
        "is_fact_query": True,
    }
    # Keine assertive cues → sentence_violations=0
    # overall_ratio ~1.0 (alles novel da evidence leer) → > 0.5 → violated in strict mode
    answer = "Alle Fakten wurden archiviert. Keine Einträge waren gefunden worden."
    checked = layer._grounding_postcheck(answer, plan, precheck)

    qv = _grounding(plan, "qualitative_violation", {})
    assert _grounding(plan, "violation_detected", False) is True, (
        f"Strict-Mode muss violation setzen. qv={qv}"
    )
    assert qv.get("overall_novelty_ratio", 0) > 0.5, (
        f"overall_novelty_ratio muss >0.5 sein: {qv}"
    )


def test_grounding_strict_mode_not_activated_when_evidence_has_content():
    """Normale evidence mit key_facts → strict mode NICHT aktiv → normaler Guard-Pfad.
    sentence_violations=0 < 1 → NOT violated (normaler Guard)."""
    layer = OutputLayer()
    plan = {}
    precheck = {
        "policy": _policy_no_numeric(),
        "evidence": [
            {
                "tool_name": "memory_graph_search",
                "status": "ok",
                "key_facts": [
                    "skill_name: hardware_info",
                    "description: Zeigt Hardware-Details an",
                ],
            }
        ],
        "is_fact_query": True,
    }
    # Antwort ohne assertive cues → sentence_violations=0 → normaler Guard: violated=False
    # (min_assertive_sentence_violations=1 → braucht mindestens 1 sentence_violation)
    answer = "Alle Fakten wurden archiviert. Keine Einträge waren gefunden worden."
    checked = layer._grounding_postcheck(answer, plan, precheck)

    # Normaler Guard: sentence_violations=0 < 1 → NOT violated
    assert checked == answer, (
        f"Normaler Guard darf nicht feuern wenn sentence_violations=0 und evidence hat content. "
        f"qv={plan.get('_grounding_qualitative_violation')}"
    )
    assert _grounding(plan, "violation_detected", False) is not True


def test_grounding_precheck_header_only_ok_evidence_uses_missing_evidence_fallback_mode():
    layer = OutputLayer()
    plan = {
        "is_fact_query": True,
        "_selected_tools_for_prompt": ["run_skill"],
    }
    set_runtime_grounding_evidence(plan, [
        {
            "tool_name": "run_skill",
            "status": "ok",
            "ref_id": "abc123",
            "key_facts": [],
        }
    ])
    with patch("core.layers.output.load_grounding_policy", return_value=_policy()):
        precheck = layer._grounding_precheck(plan, memory_data="")
    assert precheck["blocked"] is False
    assert precheck.get("mode") == "missing_evidence_fallback"
    assert _grounding(plan, "missing_evidence", False) is True
    assert _grounding(plan, "successful_evidence", 0) == 0
    assert _grounding(plan, "successful_evidence_status_only", 0) == 1


def test_grounding_precheck_accepts_carryover_evidence_with_content():
    layer = OutputLayer()
    plan = {
        "is_fact_query": True,
        "_selected_tools_for_prompt": ["run_skill"],
    }
    set_runtime_grounding_evidence(plan, [])
    set_runtime_carryover_grounding_evidence(plan, [
        {
            "tool_name": "run_skill",
            "status": "ok",
            "ref_id": "carry-1",
            "key_facts": [
                "GPU: NVIDIA GeForce RTX 2060 SUPER",
                "VRAM: 8.0 GB gesamt",
            ],
        }
    ])
    with patch("core.layers.output.load_grounding_policy", return_value=_policy()):
        precheck = layer._grounding_precheck(plan, memory_data="")
    assert precheck["blocked"] is False
    assert precheck.get("mode") == "pass"
    assert _grounding(plan, "missing_evidence", False) is False
    assert _grounding(plan, "successful_evidence", 0) == 1


def test_orchestrator_grounding_evidence_entry_formats_list_skills_compact():
    from core.orchestrator import PipelineOrchestrator

    raw = json.dumps(
        {
            "installed": [
                {"name": "current_weather", "version": "1.0.0"},
                {"name": "system_hardware_info", "version": "1.0.0"},
            ],
            "installed_count": 2,
            "available": [],
            "available_count": 0,
        }
    )
    entry = PipelineOrchestrator._build_grounding_evidence_entry(
        tool_name="list_skills",
        raw_result=raw,
        status="ok",
        ref_id="skills-compact-1",
    )

    assert "installed_count: 2" in entry.get("key_facts", [])
    assert "available_count: 0" in entry.get("key_facts", [])
    names_line = next((x for x in entry.get("key_facts", []) if x.startswith("installed_names:")), "")
    assert "current_weather" in names_line
    assert "system_hardware_info" in names_line
    structured = entry.get("structured", {})
    assert structured.get("installed_count") == 2
    assert structured.get("available_count") == 0
    assert structured.get("installed_names") == ["current_weather", "system_hardware_info"]


def test_grounding_fallback_summarizes_list_skills_naturally():
    layer = OutputLayer()
    evidence = [
        {
            "tool_name": "list_skills",
            "status": "ok",
            "key_facts": [],
            "structured": {
                "installed_count": 2,
                "available_count": 0,
                "installed_names": ["current_weather", "system_hardware_info"],
            },
        }
    ]

    out = layer._build_grounding_fallback(evidence, mode="summarize_evidence")
    assert out.startswith("Verifizierte Ergebnisse:")
    assert "list_skills: Runtime-Skills:" in out
    assert "current_weather" in out
    assert "system_hardware_info" in out
    assert "2 installiert" in out


def test_grounding_fallback_summarizes_list_skills_from_raw_json_fact_line():
    layer = OutputLayer()
    evidence = [
        {
            "tool_name": "list_skills",
            "status": "ok",
            "key_facts": [
                '{"installed":[{"name":"current_weather"},{"name":"system_hardware_info"}],"installed_count":2,"available_count":0}'
            ],
        }
    ]

    out = layer._build_grounding_fallback(evidence, mode="summarize_evidence")
    assert out.startswith("Verifizierte Ergebnisse:")
    assert "list_skills: Runtime-Skills:" in out
    assert "2 installiert" in out
    assert "current_weather" in out


def test_grounding_postcheck_uses_repair_summary_before_hard_fallback():
    layer = OutputLayer()
    plan = {}
    precheck = {
        "policy": {
            **_policy()["output"],
            "enable_postcheck_repair_once": True,
        },
        "evidence": [
            {
                "tool_name": "list_skills",
                "status": "ok",
                "key_facts": [
                    "installed_count: 2",
                    "available_count: 0",
                    "installed_names: current_weather, system_hardware_info",
                ],
            }
        ],
        "is_fact_query": True,
    }
    answer = "Du hast 72 Skills installiert und 85 weitere verfügbar."
    checked = layer._grounding_postcheck(answer, plan, precheck)

    assert checked.startswith("Verifizierte Ergebnisse:")
    assert "list_skills: Runtime-Skills:" in checked
    assert "72" not in checked and "85" not in checked
    assert _grounding(plan, "repair_used", False) is True
    assert "Ich kann nur verifizierte Fakten" not in checked


def test_grounding_postcheck_repair_can_be_disabled_by_policy():
    layer = OutputLayer()
    plan = {}
    precheck = {
        "policy": {
            **_policy()["output"],
            "enable_postcheck_repair_once": False,
        },
        "evidence": [
            {
                "tool_name": "list_skills",
                "status": "ok",
                "key_facts": [
                    "installed_count: 2",
                    "available_count: 0",
                    "installed_names: current_weather, system_hardware_info",
                ],
            }
        ],
        "is_fact_query": True,
    }
    answer = "Du hast 72 Skills installiert und 85 weitere verfügbar."
    checked = layer._grounding_postcheck(answer, plan, precheck)

    assert "Ich kann nur verifizierte Fakten aus den Tool-Ergebnissen ausgeben." in checked
    assert _grounding(plan, "repair_used", False) is not True


def test_grounding_fallback_summarizes_skill_catalog_layers_separately():
    layer = OutputLayer()
    evidence = [
        {
            "tool_name": "list_skills",
            "status": "ok",
            "structured": {
                "installed_count": 2,
                "available_count": 0,
                "installed_names": ["current_weather", "system_hardware_info"],
            },
        },
        {
            "tool_name": "skill_registry_snapshot",
            "status": "ok",
            "key_facts": [
                "active_count: 2",
                "draft_count: 1",
                "draft_names: draft_alpha",
            ],
        },
        {
            "tool_name": "skill_addons",
            "status": "ok",
            "key_facts": [
                "selected_docs: skill-tools-vs-skills, skill-answering-rules",
                "Built-in Tools sind keine installierten Runtime-Skills.",
            ],
        },
    ]

    out = layer._build_grounding_fallback(evidence, mode="summarize_evidence")
    assert "list_skills: Runtime-Skills:" in out
    assert "skill_registry_snapshot: Skill-Registry:" in out
    assert "1 Drafts" in out
    assert "skill_addons: Skill-Semantik:" in out
    assert "Built-in Tools sind keine installierten Runtime-Skills." in out


def test_skill_catalog_postcheck_repairs_persona_drift_to_safe_runtime_summary():
    layer = OutputLayer()
    plan = {
        "is_fact_query": True,
        "resolution_strategy": "skill_catalog_context",
        "_skill_catalog_context": {"installed_count": 0, "draft_count": 1},
        "_ctx_trace": {},
    }
    precheck = {
        "policy": _policy()["output"],
        "evidence": [
            {
                "tool_name": "list_skills",
                "status": "ok",
                "key_facts": [
                    "installed_count: 0",
                    "available_count: 0",
                ],
            },
            {
                "tool_name": "skill_registry_snapshot",
                "status": "ok",
                "key_facts": [
                    "draft_count: 1",
                    "draft_names: draft_alpha",
                ],
            },
            {
                "tool_name": "skill_addons",
                "status": "ok",
                "key_facts": [
                    "Built-in Tools sind keine installierten Runtime-Skills.",
                ],
            },
        ],
        "is_fact_query": True,
    }
    answer = (
        "Runtime-Skills: Im Runtime-Skill-System sind aktuell keine installierten Skills vorhanden.\n"
        "Ich habe trotzdem grundlegende Fähigkeiten: Memory, Eigenes Denken, Tools."
    )

    checked = layer._grounding_postcheck(answer, plan, precheck)

    assert checked != answer
    assert checked.startswith("Runtime-Skills:")
    assert "\nEinordnung:" in checked
    assert "keine installierten Skills vorhanden" in checked
    assert "Built-in Tools" in checked
    assert "Eigenes Denken" not in checked
    assert "grundlegende Fähigkeiten" not in checked
    assert _grounding(plan, "repair_used", False) is True
    violation = _grounding(plan, "skill_catalog_violation", {})
    assert violation.get("reason") == "free_self_description"
    assert plan["_ctx_trace"]["skill_catalog"]["postcheck"] == "repaired:free_self_description"
    assert plan["_ctx_trace"]["skill_catalog"]["strict_mode"] == "answer_schema+semantic_postcheck"


def test_skill_catalog_postcheck_repairs_unverified_session_skill_claims():
    layer = OutputLayer()
    plan = {
        "is_fact_query": True,
        "_authoritative_resolution_strategy": "skill_catalog_context",
        "_skill_catalog_context": {"installed_count": 0, "draft_count": 1},
    }
    precheck = {
        "policy": _policy()["output"],
        "evidence": [
            {
                "tool_name": "list_skills",
                "status": "ok",
                "key_facts": [
                    "installed_count: 0",
                    "available_count: 0",
                ],
            },
            {
                "tool_name": "skill_registry_snapshot",
                "status": "ok",
                "key_facts": [
                    "draft_count: 1",
                    "draft_names: draft_alpha",
                ],
            },
            {
                "tool_name": "skill_addons",
                "status": "ok",
                "key_facts": [
                    "Session-/System-Skills nur nennen, wenn sie im Kontext ausdrücklich belegt sind.",
                ],
            },
        ],
        "is_fact_query": True,
    }
    answer = (
        "Runtime-Skills: Im Runtime-Skill-System sind aktuell keine installierten Skills vorhanden.\n"
        "Einordnung: Dazu kommen Session-Skills aus SKILL.md."
    )

    checked = layer._grounding_postcheck(answer, plan, precheck)

    assert checked != answer
    assert "SKILL.md" not in checked
    assert "Session-Skills" not in checked
    assert "1 Draft-Skills" not in checked
    assert "ohne `list_draft_skills`-Evidence nicht belegt" not in checked
    violation = _grounding(plan, "skill_catalog_violation", {})
    assert violation.get("reason") == "unverified_session_system_skills"


def test_skill_catalog_postcheck_keeps_clean_structured_answer():
    layer = OutputLayer()
    plan = {
        "is_fact_query": True,
        "resolution_strategy": "skill_catalog_context",
        "_skill_catalog_context": {"installed_count": 0, "draft_count": 1},
        "_ctx_trace": {},
    }
    precheck = {
        "policy": _policy()["output"],
        "evidence": [
            {
                "tool_name": "list_skills",
                "status": "ok",
                "key_facts": [
                    "installed_count: 0",
                    "available_count: 0",
                ],
            },
            {
                "tool_name": "skill_registry_snapshot",
                "status": "ok",
                "key_facts": [
                    "draft_count: 1",
                    "draft_names: draft_alpha",
                ],
            },
            {
                "tool_name": "skill_addons",
                "status": "ok",
                "key_facts": [
                    "Built-in Tools sind keine installierten Runtime-Skills.",
                ],
            },
        ],
        "is_fact_query": True,
    }
    answer = (
        "Runtime-Skills: Im Runtime-Skill-System sind aktuell keine installierten Skills vorhanden.\n"
        "Einordnung: Built-in Tools und allgemeine Systemfähigkeiten sind davon getrennt und werden nicht als installierte Skills gezählt."
    )

    checked = layer._grounding_postcheck(answer, plan, precheck)

    assert checked == answer
    assert _grounding(plan, "repair_used", False) is not True
    assert plan["_ctx_trace"]["skill_catalog"]["postcheck"] == "passed"


def test_skill_catalog_postcheck_repairs_unsplit_followup_brainstorming():
    layer = OutputLayer()
    plan = {
        "is_fact_query": True,
        "resolution_strategy": "skill_catalog_context",
        "strategy_hints": ["runtime_skills", "fact_then_followup"],
        "_skill_catalog_context": {"installed_count": 0, "draft_count": 1},
    }
    precheck = {
        "policy": _policy()["output"],
        "evidence": [
            {
                "tool_name": "list_skills",
                "status": "ok",
                "key_facts": [
                    "installed_count: 0",
                    "available_count: 0",
                ],
            },
            {
                "tool_name": "skill_registry_snapshot",
                "status": "ok",
                "key_facts": [
                    "draft_count: 1",
                    "draft_names: draft_alpha",
                ],
            },
        ],
        "is_fact_query": True,
    }
    answer = (
        "Runtime-Skills: Im Runtime-Skill-System sind aktuell keine installierten Skills vorhanden.\n"
        "Einordnung: Built-in Tools sind davon getrennt. Ich hätte gerne bessere Analyse-Skills."
    )

    checked = layer._grounding_postcheck(answer, plan, precheck)

    assert checked != answer
    assert checked.startswith("Runtime-Skills:")
    assert "\nEinordnung:" in checked
    assert "\nNächster Schritt:" in checked
    assert "Ich hätte gerne" not in checked
    violation = _grounding(plan, "skill_catalog_violation", {})
    assert violation.get("reason") == "followup_not_split"


def test_skill_catalog_postcheck_repairs_unsolicited_action_offer_in_inventory_mode():
    layer = OutputLayer()
    plan = {
        "is_fact_query": True,
        "resolution_strategy": "skill_catalog_context",
        "_skill_catalog_policy": {
            "mode": "inventory_read_only",
            "required_tools": ["list_skills"],
            "force_sections": ["Runtime-Skills", "Einordnung"],
        },
        "_skill_catalog_context": {"installed_count": 0},
    }
    precheck = {
        "policy": _policy()["output"],
        "evidence": [
            {
                "tool_name": "list_skills",
                "status": "ok",
                "key_facts": [
                    "installed_count: 0",
                    "available_count: 0",
                ],
            },
        ],
        "is_fact_query": True,
    }
    answer = (
        "Runtime-Skills: Im Runtime-Skill-System sind aktuell keine installierten Skills vorhanden.\n"
        "Einordnung: Das bedeutet, dass noch keine zusätzlichen Funktionen aktiviert wurden.\n\n"
        "Möchtest du, dass ich einen speziellen Skill entwickle oder hast du eine konkrete Aufgabe im Sinn?"
    )

    checked = layer._grounding_postcheck(answer, plan, precheck)

    assert checked != answer
    assert checked.startswith("Runtime-Skills:")
    assert "\nEinordnung:" in checked
    assert "Möchtest du" not in checked
    violation = _grounding(plan, "skill_catalog_violation", {})
    assert violation.get("reason") == "unsolicited_action_offer"


def test_skill_catalog_postcheck_safe_fallback_uses_wunsch_skills_heading_when_policy_requires_it():
    layer = OutputLayer()
    plan = {
        "is_fact_query": True,
        "resolution_strategy": "skill_catalog_context",
        "strategy_hints": ["runtime_skills", "tools_vs_skills", "fact_then_followup"],
        "_skill_catalog_policy": {
            "mode": "inventory_read_only",
            "required_tools": ["list_skills"],
            "force_sections": ["Runtime-Skills", "Einordnung", "Wunsch-Skills"],
            "followup_split_required": True,
        },
        "_skill_catalog_context": {"installed_count": 0},
        "_ctx_trace": {},
    }
    precheck = {
        "policy": _policy()["output"],
        "evidence": [
            {
                "tool_name": "list_skills",
                "status": "ok",
                "key_facts": [
                    "installed_count: 0",
                    "available_count: 0",
                ],
            },
            {
                "tool_name": "skill_addons",
                "status": "ok",
                "key_facts": [
                    "Built-in Tools sind keine installierten Runtime-Skills.",
                ],
            },
        ],
        "is_fact_query": True,
    }
    answer = (
        "Runtime-Skills: Im Runtime-Skill-System sind aktuell keine installierten Skills vorhanden. "
        "Ich habe aber viele eingebaute Tools und allgemeine Faehigkeiten.\n"
        "Einordnung: list_skills zeigt nur installierte Runtime-Skills."
    )

    checked = layer._grounding_postcheck(answer, plan, precheck)

    assert checked != answer
    assert checked.startswith("Runtime-Skills:")
    assert "\nEinordnung:" in checked
    assert "\nWunsch-Skills:" in checked
    assert "\nNächster Schritt:" not in checked
    violation = _grounding(plan, "skill_catalog_violation", {})
    assert violation.get("reason") == "runtime_tool_category_leakage"


def test_skill_catalog_postcheck_repairs_unverified_draft_state_claim_without_list_draft_skills():
    layer = OutputLayer()
    plan = {
        "is_fact_query": True,
        "resolution_strategy": "skill_catalog_context",
        "strategy_hints": ["tools_vs_skills"],
        "_skill_catalog_policy": {
            "mode": "inventory_read_only",
            "required_tools": ["list_skills"],
            "force_sections": ["Runtime-Skills", "Einordnung"],
            "draft_explanation_required": True,
        },
        "_skill_catalog_context": {"installed_count": 0, "draft_count": 1},
    }
    precheck = {
        "policy": _policy()["output"],
        "evidence": [
            {
                "tool_name": "list_skills",
                "status": "ok",
                "key_facts": [
                    "installed_count: 0",
                    "available_count: 0",
                ],
            },
            {
                "tool_name": "skill_registry_snapshot",
                "status": "ok",
                "key_facts": [
                    "draft_count: 1",
                    "draft_names: draft_alpha",
                ],
            },
            {
                "tool_name": "skill_addons",
                "status": "ok",
                "key_facts": [
                    "Built-in Tools sind keine installierten Runtime-Skills.",
                ],
            },
        ],
        "is_fact_query": True,
    }
    answer = (
        "Runtime-Skills: Im Runtime-Skill-System sind aktuell keine installierten Skills vorhanden.\n"
        "Einordnung: Draft-Skills sind aktuell nicht verifiziert verfuegbar, da die Registry keine verfuegbaren Skills anzeigt."
    )

    checked = layer._grounding_postcheck(answer, plan, precheck)

    assert checked != answer
    assert checked.startswith("Runtime-Skills:")
    assert "ohne `list_draft_skills`-Evidence nicht belegt" in checked
    assert "draft_alpha" not in checked
    violation = _grounding(plan, "skill_catalog_violation", {})
    assert violation.get("reason") == "draft_claim_without_inventory_evidence"


def test_skill_catalog_postcheck_repairs_with_list_draft_skills_evidence():
    layer = OutputLayer()
    plan = {
        "is_fact_query": True,
        "resolution_strategy": "skill_catalog_context",
        "strategy_hints": ["draft_skills", "tools_vs_skills"],
        "_skill_catalog_context": {"installed_count": 0},
        "_ctx_trace": {},
    }
    precheck = {
        "policy": _policy()["output"],
        "evidence": [
            {
                "tool_name": "list_skills",
                "status": "ok",
                "key_facts": [
                    "installed_count: 0",
                    "available_count: 0",
                ],
            },
            {
                "tool_name": "list_draft_skills",
                "status": "ok",
                "structured": {
                    "draft_count": 2,
                    "draft_names": ["draft_alpha", "draft_beta"],
                },
                "key_facts": [
                    "draft_count: 2",
                    "draft_names: draft_alpha, draft_beta",
                ],
            },
            {
                "tool_name": "skill_addons",
                "status": "ok",
                "key_facts": [
                    "Built-in Tools sind keine installierten Runtime-Skills.",
                ],
            },
        ],
        "is_fact_query": True,
    }
    answer = "Draft-Skills: draft_alpha, draft_beta."

    checked = layer._grounding_postcheck(answer, plan, precheck)

    assert checked != answer
    assert checked.startswith("Runtime-Skills:")
    assert "draft_alpha" in checked
    assert "draft_beta" in checked
    assert "list_skills" in checked
    assert "nicht aufgefuehrt" in checked
    assert plan["_ctx_trace"]["skill_catalog"]["postcheck"] == "repaired:missing_runtime_section"
