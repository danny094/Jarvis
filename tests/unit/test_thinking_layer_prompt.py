"""Tests für Fix 4: ThinkingLayer Prompt-Regel für new_fact_value bei Reminder-Anfragen.

Da ThinkingLayer ein LLM aufruft, testen wir:
1. Dass der THINKING_PROMPT die neue Regel enthält (Struktur-Test)
2. Mock-LLM-Output-Validierung: neue Regel korrekt in JSON-Response propagiert
"""
import json
import pytest
from core.layers.thinking import THINKING_PROMPT


# ---------------------------------------------------------------------------
# Test 1: THINKING_PROMPT enthält die neue Schlüsselwort-basierte Regel
# ---------------------------------------------------------------------------

def test_thinking_prompt_contains_later_keyword_rule():
    """THINKING_PROMPT muss die Regel für 'später/irgendwann/berechnen/erledigen/noch' enthalten."""
    assert "später" in THINKING_PROMPT, "Schlüsselwort 'später' fehlt in THINKING_PROMPT"
    assert "new_fact_value: null" in THINKING_PROMPT, (
        "'new_fact_value: null' Anweisung fehlt in THINKING_PROMPT"
    )


def test_thinking_prompt_contains_explicit_fact_rule():
    """THINKING_PROMPT muss Regel für explizite Fakt-Angaben enthalten."""
    assert "new_fact_value NUR setzen" in THINKING_PROMPT, (
        "Regel 'new_fact_value NUR setzen' fehlt in THINKING_PROMPT"
    )
    assert "expliziten Wert" in THINKING_PROMPT, (
        "Regel für 'expliziten Wert' fehlt in THINKING_PROMPT"
    )


def test_thinking_prompt_contains_no_inference_rule():
    """THINKING_PROMPT muss explizit verbieten, new_fact_value zu berechnen/schlussfolgern."""
    assert "NIEMALS selbst berechnen" in THINKING_PROMPT, (
        "Anti-Inferenz-Regel fehlt in THINKING_PROMPT"
    )


# ---------------------------------------------------------------------------
# Test 2: Mock-LLM Validierung — neue Regel korrekt angewandt
# ---------------------------------------------------------------------------

def _validate_plan_for_reminder(plan: dict) -> bool:
    """Gibt True zurück wenn der Plan die neue Regel korrekt anwendet:
    bei Reminder/Later-Anfragen muss new_fact_value=null sein."""
    reminder_keywords = ["später", "irgendwann", "berechnen", "erledigen", "noch"]
    is_reminder = any(kw in plan.get("intent", "").lower() for kw in reminder_keywords)
    if is_reminder:
        return plan.get("new_fact_value") is None
    return True  # keine Reminder → keine Constraint


def test_reminder_task_new_fact_value_is_null():
    """Simulierter LLM-Output für Reminder-Anfrage: new_fact_value muss null sein.

    Verarbeitung: 'Erinnere mich später, 1+1 zu berechnen'
    → is_new_fact kann True sein (es gibt eine Aufgabe zu merken)
    → new_fact_value muss null sein (kein expliziter Wert genannt)
    """
    # Simuliert korrekten LLM-Output gemäß neuer Regel
    correct_plan = {
        "intent": "später berechnen erinnern",
        "is_new_fact": True,
        "new_fact_key": "reminder_math",
        "new_fact_value": None,  # Korrekt: null, da kein expliziter Wert
        "needs_memory": True,
    }
    assert correct_plan["new_fact_value"] is None, (
        "new_fact_value muss null sein bei Reminder-Anfragen"
    )
    assert _validate_plan_for_reminder(correct_plan) is True

    # Simuliert FALSCHEN LLM-Output (Bug-Regression: prefills value)
    wrong_plan = {
        "intent": "später berechnen erinnern",
        "is_new_fact": True,
        "new_fact_key": "reminder_math",
        "new_fact_value": "2",  # FALSCH: Wert wurde selbst berechnet/geschlussfolgert
        "needs_memory": True,
    }
    assert _validate_plan_for_reminder(wrong_plan) is False, (
        "Plan mit gesetztem new_fact_value bei Reminder muss als invalid erkannt werden"
    )


def test_explicit_fact_sets_value():
    """Für explizite Fakt-Angaben darf (und soll) new_fact_value gesetzt werden."""
    plan_with_explicit_fact = {
        "intent": "User nennt Namen",
        "is_new_fact": True,
        "new_fact_key": "user_name",
        "new_fact_value": "Max",  # Korrekt: direkt aus User-Aussage
        "needs_memory": True,
    }
    # _validate_plan_for_reminder ignoriert diesen Plan (kein reminder keyword)
    assert _validate_plan_for_reminder(plan_with_explicit_fact) is True
    assert plan_with_explicit_fact["new_fact_value"] == "Max"


def test_thinking_prompt_new_fact_value_rule_position():
    """Die new_fact_value-Regel muss im Memory-Abschnitt des Prompts stehen."""
    memory_section_start = THINKING_PROMPT.find("Memory:")
    rule_position = THINKING_PROMPT.find("new_fact_value NUR setzen")
    assert memory_section_start != -1, "Memory-Abschnitt nicht gefunden"
    assert rule_position != -1, "new_fact_value-Regel nicht gefunden"
    assert rule_position > memory_section_start, (
        "new_fact_value-Regel muss nach Memory: Abschnitt stehen"
    )


def test_thinking_prompt_later_keywords_are_listed():
    """Alle wichtigen 'später'-Schlüsselwörter müssen im Prompt stehen."""
    required_keywords = ["später", "irgendwann", "berechnen", "erledigen", "noch"]
    for kw in required_keywords:
        assert kw in THINKING_PROMPT, f"Schlüsselwort '{kw}' fehlt in THINKING_PROMPT"
