from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_commander_exposes_trion_debug_route_and_direct_llm_analysis():
    src = _read("adapters/admin-api/commander_api/containers.py")
    assert '@router.post("/containers/{container_id}/trion-debug")' in src
    assert '@router.post("/containers/{container_id}/trion-shell/start")' in src
    assert '@router.post("/containers/{container_id}/trion-shell/step")' in src
    assert '@router.post("/containers/{container_id}/trion-shell/stop")' in src
    assert "exec_in_container_detailed" in src
    assert "get_container_logs" in src
    assert "get_container_stats" in src
    assert "def _remember_container_state(" in src
    assert "complete_chat(" in src
    assert 'resolve_role_provider("output", default="ollama")' in src
    assert '"Do not use tools.' in src
    assert '"missing_api_key" in str(llm_err).lower()' in src
    assert 'provider = "ollama"' in src
    assert 'workspace_event_save' in src
    assert 'TRION controlling an attached interactive container shell' in src
    assert "def _classify_shell_action(" in src
    assert "def _verify_previous_shell_action(" in src
    assert "def _detect_shell_blocker(" in src
    assert "def _action_verification_focus(" in src
    assert "def _build_structured_shell_summary(" in src
    assert "load_container_addon_context" in src
    assert "Relevant container addon context:" in src
    assert "Inferred container addon tags:" in src
    assert '"addon_docs": list(addon_context.get("selected_docs") or [])' in src
    assert "If the runtime facts or addon context indicate supervisord, do not use systemctl." in src
    assert "loop_guard_repeat" in src
    assert "gui_dialog_still_open" in src
    assert "interactive_prompt_waiting" in src
    assert '"changes_made"' in src
    assert '"summary_parts"' in src
    assert '"action_type"' in src
    assert "Action history:" in src
