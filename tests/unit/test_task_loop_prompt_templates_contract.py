from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TASK_LOOP_PROMPTS = ROOT / "intelligence_modules" / "prompts" / "task_loop"


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_task_loop_step_runtime_template_exists_and_documents_boundary():
    assert (TASK_LOOP_PROMPTS / "step_runtime.md").is_file()
    assert (TASK_LOOP_PROMPTS / "status.md").is_file()
    assert (TASK_LOOP_PROMPTS / "clarification.md").is_file()
    for name in [
        "risk_gate.md",
        "control_soft_block.md",
        "hard_block.md",
        "waiting.md",
        "verify_before_complete.md",
        "chat_default_step_1.md",
        "chat_default_step_2.md",
        "chat_default_step_3.md",
        "chat_default_fallback.md",
        "chat_analysis_step_1.md",
        "chat_analysis_step_2.md",
        "chat_analysis_step_3.md",
        "chat_analysis_fallback.md",
        "chat_validation_step_1.md",
        "chat_validation_step_2.md",
        "chat_validation_step_3.md",
        "chat_validation_fallback.md",
        "chat_implementation_step_1.md",
        "chat_implementation_step_2.md",
        "chat_implementation_step_3.md",
        "chat_implementation_fallback.md",
        "container_python_missing_parameters.md",
        "container_generic_missing_parameters.md",
        "container_recognized_parameters.md",
        "container_blueprint_choice.md",
        "container_single_blueprint_choice.md",
    ]:
        assert (TASK_LOOP_PROMPTS / name).is_file()

    readme = (TASK_LOOP_PROMPTS / "README.md").read_text(encoding="utf-8")
    assert "step_runtime.md" in readme
    assert "risk_gate.md" in readme
    assert "Step selection" in readme
    assert "recovery decisions" in readme
    assert "container_*.md" in readme


def test_task_loop_step_runtime_prompt_uses_prompt_loader():
    src = _read("core/task_loop/step_runtime/prompting.py")

    assert "from intelligence_modules.prompt_manager import load_prompt" in src
    assert 'load_prompt(\n        "task_loop",\n        "step_runtime",' in src
    assert 'f"Task-Loop Schritt {current_step_index}/{total_steps}' not in src


def test_task_loop_completion_message_uses_status_template():
    src = _read("core/task_loop/completion_policy.py")

    assert "from intelligence_modules.prompt_manager import load_prompt" in src
    assert '"task_loop",' in src
    assert '"status",' in src
    assert "Task-Loop abgeschlossen." not in src

    stream_src = _read("core/task_loop/runner/chat_stream.py")
    assert "build_completion_message(completed)" in stream_src
    assert '"\\nFinaler Planstatus:\\n"' not in stream_src


def test_task_loop_concrete_input_message_uses_clarification_template():
    src = _read("core/task_loop/chat_runtime.py")

    assert "from intelligence_modules.prompt_manager import load_prompt" in src
    assert 'load_prompt("task_loop", "clarification")' in src
    assert "Fuer diesen Schritt brauche ich eine konkrete Antwort" not in src

    template = (TASK_LOOP_PROMPTS / "clarification.md").read_text(encoding="utf-8")
    assert "Fuer diesen Schritt brauche ich eine konkrete Antwort" in template


def test_task_loop_runner_messages_use_templates():
    src = _read("core/task_loop/runner/messages.py")

    assert "from intelligence_modules.prompt_manager import load_prompt" in src
    for template_name in [
        "risk_gate",
        "control_soft_block",
        "hard_block",
        "waiting",
        "verify_before_complete",
    ]:
        assert f'"{template_name}"' in src

    forbidden_inline_markers = [
        "brauche ich deine Freigabe",
        "Ich brauche deine Bestätigung bevor ich weitermache",
        "Dieser Schritt wurde blockiert",
        "Ich brauche mehr Informationen um weiterzumachen",
        "Ich prüfe das Ergebnis noch kurz gegen belastbare Hinweise",
    ]
    for marker in forbidden_inline_markers:
        assert marker not in src


def test_task_loop_default_step_answers_use_templates():
    src = _read("core/task_loop/step_answers.py")

    assert "from intelligence_modules.prompt_manager import load_prompt" in src
    for template_name in [
        "chat_default_step_1",
        "chat_default_step_2",
        "chat_default_step_3",
        "chat_default_fallback",
    ]:
        assert f'"{template_name}"' in src

    forbidden_inline_markers = [
        "Erfolg heisst, dass der naechste Schritt konkret",
        "Naechster sicherer Schritt: im Chat bleiben",
        "Kein riskanter Pfad wird automatisch ausgefuehrt",
        "Status: Die Aufgabe ist im sicheren Chat-Rahmen sortiert",
    ]
    for marker in forbidden_inline_markers:
        assert marker not in src


def test_task_loop_analysis_step_answers_use_templates():
    src = _read("core/task_loop/step_answers.py")

    for template_name in [
        "chat_analysis_step_1",
        "chat_analysis_step_2",
        "chat_analysis_step_3",
        "chat_analysis_fallback",
    ]:
        assert f'"{template_name}"' in src

    forbidden_inline_markers = [
        "Fragestellung:",
        "Einflussfaktoren: expliziter Multistep-Start",
        "Unsicherheiten:",
        "Zwischenfazit: Der sichere Analysepfad ist abgeschlossen",
    ]
    for marker in forbidden_inline_markers:
        assert marker not in src


def test_task_loop_validation_step_answers_use_templates():
    src = _read("core/task_loop/step_answers.py")

    for template_name in [
        "chat_validation_step_1",
        "chat_validation_step_2",
        "chat_validation_step_3",
        "chat_validation_fallback",
    ]:
        assert f'"{template_name}"' in src

    forbidden_inline_markers = [
        "Pruefziel:",
        "Beobachtbare Kriterien:",
        "Befund: Der aktuelle Pfad bleibt sicher",
        "Zusammenfassung: Die Pruefung ist als Chat-only Zwischenstand abgeschlossen",
    ]
    for marker in forbidden_inline_markers:
        assert marker not in src


def test_task_loop_implementation_step_answers_use_templates():
    src = _read("core/task_loop/step_answers.py")

    for template_name in [
        "chat_implementation_step_1",
        "chat_implementation_step_2",
        "chat_implementation_step_3",
        "chat_implementation_fallback",
    ]:
        assert f'"{template_name}"' in src

    forbidden_inline_markers = [
        "Zielbild:",
        "Umsetzungsschnitt:",
        "Gate-Bewertung:",
        "Naechster Implementierungsschnitt:",
    ]
    for marker in forbidden_inline_markers:
        assert marker not in src


def test_task_loop_container_request_messages_use_templates():
    parameter_src = _read("core/task_loop/capabilities/container/parameter_policy.py")
    request_src = _read("core/task_loop/capabilities/container/request_policy.py")

    assert "from intelligence_modules.prompt_manager import load_prompt" in parameter_src
    assert "from intelligence_modules.prompt_manager import load_prompt" in request_src
    for template_name in [
        "container_python_missing_parameters",
        "container_generic_missing_parameters",
        "container_recognized_parameters",
    ]:
        assert f'"{template_name}"' in parameter_src
    for template_name in [
        "container_blueprint_choice",
        "container_single_blueprint_choice",
    ]:
        assert f'"{template_name}"' in request_src

    combined = parameter_src + "\n" + request_src
    forbidden_inline_markers = [
        "Ich brauche noch Angaben fuer die Python-Container-Anfrage.",
        "Bitte nenne mindestens den gewuenschten Blueprint oder die Basis",
        "Ich brauche noch Angaben fuer die Container-Anfrage.",
        "Bitte nenne mindestens den gewuenschten Blueprint oder ein Ressourcenprofil",
        "Bereits erkannt:",
        "Ich habe mehrere verifizierte Blueprint-Optionen gefunden.",
        "Bitte waehle eine davon:",
        "Verfuegbarer Blueprint:",
        "Ich kann damit weiterarbeiten, wenn du willst",
    ]
    for marker in forbidden_inline_markers:
        assert marker not in combined
