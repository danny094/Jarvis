import json
from unittest.mock import patch

from core.layers.output import OutputLayer


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


def test_grounding_precheck_blocks_fact_query_without_evidence():
    layer = OutputLayer()
    plan = {
        "is_fact_query": True,
        "suggested_tools": ["get_system_info"],
        "_grounding_evidence": [],
    }
    with patch("core.layers.output.load_grounding_policy", return_value=_policy()):
        precheck = layer._grounding_precheck(plan, memory_data="")
    assert precheck["blocked"] is True
    assert plan.get("_grounding_missing_evidence") is True
    assert "keinen verifizierten tool-nachweis" in precheck["response"].lower()


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
    assert plan.get("_grounding_violation_detected") is True
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
    assert plan.get("_grounding_violation_detected") is not True


def test_grounding_precheck_strict_fact_mode_returns_evidence_summary():
    layer = OutputLayer()
    plan = {
        "is_fact_query": True,
        "_tool_results": "[TOOL-CARD: get_system_info | ✅ ok | ref:abc]",
        "_grounding_evidence": [
            {
                "tool_name": "get_system_info",
                "status": "ok",
                "structured": {
                    "output": "GPU: NVIDIA GeForce RTX 2060 SUPER\nVRAM total: 8192 MiB\nVRAM frei: 792 MiB"
                },
                "key_facts": [],
            }
        ],
    }
    policy = _policy()
    policy["output"]["fact_query_response_mode"] = "evidence_summary"
    with patch("core.layers.output.load_grounding_policy", return_value=policy):
        precheck = layer._grounding_precheck(plan, memory_data="")
    assert precheck["blocked"] is True
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
    assert plan.get("_grounding_violation_detected") is True
    assert plan.get("_grounding_qualitative_violation", {}).get("violated") is True


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
    assert plan.get("_grounding_violation_detected") is not True


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
    assert plan.get("_grounding_violation_detected") is not True


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
    assert plan.get("_grounding_violation_detected") is True


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

    qv = plan.get("_grounding_qualitative_violation", {})
    assert plan.get("_grounding_violation_detected") is True, (
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
    assert plan.get("_grounding_violation_detected") is not True


def test_grounding_precheck_treats_header_only_ok_evidence_as_missing():
    layer = OutputLayer()
    plan = {
        "is_fact_query": True,
        "_selected_tools_for_prompt": ["run_skill"],
        "_grounding_evidence": [
            {
                "tool_name": "run_skill",
                "status": "ok",
                "ref_id": "abc123",
                "key_facts": [],
            }
        ],
    }
    with patch("core.layers.output.load_grounding_policy", return_value=_policy()):
        precheck = layer._grounding_precheck(plan, memory_data="")
    assert precheck["blocked"] is True
    assert plan.get("_grounding_missing_evidence") is True
    assert plan.get("_grounding_successful_evidence") == 0
    assert plan.get("_grounding_successful_evidence_status_only") == 1


def test_grounding_precheck_accepts_carryover_evidence_with_content():
    layer = OutputLayer()
    plan = {
        "is_fact_query": True,
        "_selected_tools_for_prompt": ["run_skill"],
        "_grounding_evidence": [],
        "_carryover_grounding_evidence": [
            {
                "tool_name": "run_skill",
                "status": "ok",
                "ref_id": "carry-1",
                "key_facts": [
                    "GPU: NVIDIA GeForce RTX 2060 SUPER",
                    "VRAM: 8.0 GB gesamt",
                ],
            }
        ],
    }
    with patch("core.layers.output.load_grounding_policy", return_value=_policy()):
        precheck = layer._grounding_precheck(plan, memory_data="")
    assert precheck["blocked"] is False
    assert plan.get("_grounding_missing_evidence") is False
    assert plan.get("_grounding_successful_evidence") == 1


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
    assert "list_skills: Skills:" in out
    assert "current_weather" in out
    assert "system_hardware_info" in out
    assert "2 installiert" in out


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
    assert "list_skills: Skills:" in checked
    assert "72" not in checked and "85" not in checked
    assert plan.get("_grounding_repair_used") is True
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
    assert plan.get("_grounding_repair_used") is not True
