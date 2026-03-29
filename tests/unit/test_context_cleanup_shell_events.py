"""
Contract tests: core/context_cleanup.py — Shell-Event-Handler

Prüft:
- shell_session_summary erzeugt TypedFact SHELL_SESSION_SUMMARY
- shell_session_summary updated container entity (_EntityState)
- trion_shell_summary (alias) wird identisch verarbeitet
- shell_checkpoint erzeugt TypedFact SHELL_CHECKPOINT
- shell_checkpoint updated container entity
- Fehlende/leere Felder brechen nichts (fail-closed)

API-Hinweise:
- state.facts: Dict[str, List[TypedFact]] — Key ist fact_type
- state.entities: Dict[str, _EntityState] — Values sind Objekte mit Attributen
"""

from core.context_cleanup import TypedState, _apply_event


def _make_event(event_type: str, data: dict) -> dict:
    return {
        "id": "test-id-1",
        "event_type": event_type,
        "event_data": data,
        "created_at": "2026-03-29T08:00:00Z",
    }


# ---------------------------------------------------------------------------
# shell_session_summary
# ---------------------------------------------------------------------------

def test_shell_session_summary_creates_typed_fact():
    state = TypedState()
    event = _make_event("shell_session_summary", {
        "container_id": "ctr-abc123",
        "blueprint_id": "bp-test",
        "goal": "Fix noVNC blackscreen",
        "findings": "supervisord was not running",
        "changes_applied": "restarted supervisord",
        "open_blocker": "",
        "step_count": 4,
    })
    _apply_event(state, event)

    assert "SHELL_SESSION_SUMMARY" in state.facts
    facts = state.facts["SHELL_SESSION_SUMMARY"]
    assert len(facts) == 1
    assert "ctr-abc" in facts[0].value
    assert "Fix noVNC" in facts[0].value


def test_shell_session_summary_updates_container_entity():
    state = TypedState()
    event = _make_event("shell_session_summary", {
        "container_id": "ctr-abc123",
        "blueprint_id": "bp-test",
        "goal": "Test goal",
        "step_count": 2,
    })
    _apply_event(state, event)

    assert "ctr-abc123" in state.entities
    entity = state.entities["ctr-abc123"]
    assert entity.last_action == "shell_session_ended"


def test_shell_session_summary_updates_container_store():
    state = TypedState()
    event = _make_event("shell_session_summary", {
        "container_id": "ctr-abc123",
        "blueprint_id": "bp-x",
        "goal": "",
        "step_count": 1,
    })
    _apply_event(state, event)
    assert "ctr-abc123" in state.containers


def test_shell_session_summary_findings_in_fact_value():
    state = TypedState()
    event = _make_event("shell_session_summary", {
        "container_id": "ctr-test",
        "goal": "check disk",
        "findings": "disk nearly full",
        "changes_applied": "deleted logs",
        "open_blocker": "sdd not mounted",
        "step_count": 6,
    })
    _apply_event(state, event)
    fact_value = state.facts["SHELL_SESSION_SUMMARY"][0].value
    assert "disk nearly full" in fact_value
    assert "deleted logs" in fact_value
    assert "sdd not mounted" in fact_value
    assert "steps=6" in fact_value


# ---------------------------------------------------------------------------
# trion_shell_summary alias
# ---------------------------------------------------------------------------

def test_trion_shell_summary_alias_creates_typed_fact():
    """Alter event_type muss identisch zum neuen verarbeitet werden."""
    state = TypedState()
    event = _make_event("trion_shell_summary", {
        "container_id": "ctr-old",
        "blueprint_id": "bp-old",
        "summary": "Legacy summary text",
        "goal": "Old goal",
        "step_count": 3,
    })
    _apply_event(state, event)

    assert "SHELL_SESSION_SUMMARY" in state.facts


def test_trion_shell_summary_alias_updates_container():
    state = TypedState()
    event = _make_event("trion_shell_summary", {
        "container_id": "ctr-legacy",
        "blueprint_id": "",
        "step_count": 0,
    })
    _apply_event(state, event)
    assert "ctr-legacy" in state.entities
    assert state.entities["ctr-legacy"].last_action == "shell_session_ended"


def test_trion_shell_summary_uses_summary_field_as_findings_fallback():
    """Wenn 'findings' fehlt, soll 'summary' als Fallback genutzt werden."""
    state = TypedState()
    event = _make_event("trion_shell_summary", {
        "container_id": "ctr-legacy",
        "summary": "old summary text used as findings",
        "goal": "legacy goal",
        "step_count": 1,
    })
    _apply_event(state, event)
    fact_value = state.facts["SHELL_SESSION_SUMMARY"][0].value
    assert "old summary text" in fact_value


# ---------------------------------------------------------------------------
# shell_checkpoint
# ---------------------------------------------------------------------------

def test_shell_checkpoint_creates_typed_fact():
    state = TypedState()
    event = _make_event("shell_checkpoint", {
        "container_id": "ctr-xyz",
        "blueprint_id": "bp-chk",
        "goal": "Diagnose crash",
        "finding": "OOM killer triggered",
        "action_taken": "checked dmesg",
        "blocker": "",
        "step_count": 3,
    })
    _apply_event(state, event)

    assert "SHELL_CHECKPOINT" in state.facts
    fact_value = state.facts["SHELL_CHECKPOINT"][0].value
    assert "ctr-xyz" in fact_value
    assert "dmesg" in fact_value


def test_shell_checkpoint_updates_container_entity():
    state = TypedState()
    event = _make_event("shell_checkpoint", {
        "container_id": "ctr-xyz",
        "blueprint_id": "",
        "finding": "disk full",
        "action_taken": "df -h",
        "blocker": "disk full",
        "step_count": 2,
    })
    _apply_event(state, event)

    assert "ctr-xyz" in state.entities
    entity = state.entities["ctr-xyz"]
    assert entity.last_action == "shell_checkpoint"
    assert "disk full" in (entity.last_error or "")


def test_shell_checkpoint_no_fact_when_empty_finding_and_action():
    """Kein TypedFact wenn finding und action_taken beide leer."""
    state = TypedState()
    event = _make_event("shell_checkpoint", {
        "container_id": "ctr-empty",
        "finding": "",
        "action_taken": "",
        "blocker": "",
        "step_count": 1,
    })
    _apply_event(state, event)
    assert "SHELL_CHECKPOINT" not in state.facts


# ---------------------------------------------------------------------------
# Fail-closed: kaputte payloads brechen nichts
# ---------------------------------------------------------------------------

def test_shell_session_summary_missing_container_id_no_crash():
    state = TypedState()
    event = _make_event("shell_session_summary", {
        "goal": "some goal",
    })
    _apply_event(state, event)
    # kein crash; fact wird trotzdem erzeugt (container_id ist leer-string)
    assert "SHELL_SESSION_SUMMARY" in state.facts


def test_shell_checkpoint_completely_empty_payload_no_crash():
    state = TypedState()
    event = _make_event("shell_checkpoint", {})
    _apply_event(state, event)
    # kein crash, kein fact (finding und action leer)
    assert "SHELL_CHECKPOINT" not in state.facts


def test_shell_session_summary_none_values_no_crash():
    state = TypedState()
    event = _make_event("shell_session_summary", {
        "container_id": None,
        "goal": None,
        "findings": None,
        "step_count": None,
    })
    _apply_event(state, event)
    # kein crash


def test_multiple_shell_events_accumulate_facts():
    """Mehrere Shell-Events für denselben Container akkumulieren Facts."""
    state = TypedState()

    _apply_event(state, _make_event("shell_checkpoint", {
        "container_id": "ctr-multi",
        "finding": "first finding",
        "action_taken": "ls -la",
        "step_count": 1,
    }))
    _apply_event(state, _make_event("shell_session_summary", {
        "container_id": "ctr-multi",
        "goal": "check container",
        "findings": "all good",
        "step_count": 5,
    }))

    assert "SHELL_CHECKPOINT" in state.facts
    assert "SHELL_SESSION_SUMMARY" in state.facts
    # Letztes Event setzt last_action
    assert state.entities["ctr-multi"].last_action == "shell_session_ended"
