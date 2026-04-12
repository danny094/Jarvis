from core.task_loop.contracts import RiskLevel
from core.task_loop.planner import (
    build_task_loop_steps,
    clean_task_loop_objective,
    create_task_loop_snapshot_from_plan,
)


def test_clean_task_loop_objective_removes_explicit_marker():
    assert (
        clean_task_loop_objective(
            "Bitte schrittweise einen Plan machen: Pruefe den neuen Loop"
        )
        == "Pruefe den neuen Loop"
    )


def test_build_task_loop_steps_uses_thinking_intent_and_reasoning():
    steps = build_task_loop_steps(
        "Bitte schrittweise arbeiten: Pruefe den Loop",
        thinking_plan={
            "intent": "Loop-Architektur pruefen",
            "reasoning": "Erst sicheren Rahmen validieren",
            "hallucination_risk": "low",
            "suggested_tools": [],
        },
    )

    assert steps[0].title == "Pruefziel festlegen: Loop-Architektur pruefen"
    assert "Planhinweis" in steps[1].goal
    assert "Thinking-Hinweis" not in steps[1].goal
    assert all(step.risk_level is RiskLevel.SAFE for step in steps)


def test_build_task_loop_steps_hides_fallback_reasoning_from_user_visible_plan():
    steps = build_task_loop_steps(
        "Bitte schrittweise arbeiten: Pr\u00fcfe kurz den neuen Multistep Loop",
        thinking_plan={
            "intent": "unknown",
            "reasoning": "Fallback - Analyse fehlgeschlagen",
            "hallucination_risk": "low",
            "suggested_tools": [],
        },
    )

    titles = [step.title for step in steps]
    visible_text = " ".join([step.title + " " + step.goal for step in steps])

    assert titles[0].startswith("Pruefziel festlegen:")
    assert titles[1] == "Beobachtbare Kriterien definieren"
    assert "Plan in sichere Chat-Schritte schneiden" not in titles
    assert "Fallback" not in visible_text
    assert "Analyse fehlgeschlagen" not in visible_text


def test_build_task_loop_steps_uses_implementation_template():
    steps = build_task_loop_steps(
        "Bitte schrittweise arbeiten: Implementiere Auto-Continue Gates",
        thinking_plan={"intent": "Auto-Continue Gates umsetzen", "suggested_tools": []},
    )

    assert steps[0].title == "Zielbild konkretisieren: Auto-Continue Gates umsetzen"
    assert steps[1].title == "Umsetzungsschritte trennen"
    assert steps[3].title == "Naechsten Implementierungsschnitt festlegen"


def test_build_task_loop_steps_uses_analysis_template():
    steps = build_task_loop_steps(
        "Bitte schrittweise arbeiten: Analysiere warum der Loop stoppt",
        thinking_plan={"intent": "Loop-Stop analysieren", "suggested_tools": []},
    )

    assert steps[0].title == "Fragestellung eingrenzen: Loop-Stop analysieren"
    assert steps[1].title == "Einflussfaktoren sammeln"
    assert steps[2].title == "Unsicherheiten und Stopgruende pruefen"


def test_build_task_loop_steps_unknown_objective_has_non_smoke_default():
    steps = build_task_loop_steps(
        "Bitte schrittweise arbeiten: Sortiere die offenen Punkte",
        thinking_plan={},
    )

    assert steps[0].title == "Aufgabe konkretisieren: Sortiere die offenen Punkte"
    assert steps[1].title == "Naechsten sicheren Schritt bestimmen"
    assert "Plan in sichere Chat-Schritte schneiden" not in [step.title for step in steps]


def test_build_task_loop_steps_marks_tool_steps_as_needing_confirmation():
    steps = build_task_loop_steps(
        "Bitte schrittweise arbeiten: starte einen Container",
        thinking_plan={
            "intent": "Container starten",
            "hallucination_risk": "low",
            "suggested_tools": ["request_container"],
        },
    )

    assert steps[2].risk_level is RiskLevel.NEEDS_CONFIRMATION
    assert steps[2].requires_user is True
    assert steps[2].suggested_tools == ["request_container"]


def test_create_task_loop_snapshot_carries_structured_plan_steps():
    snapshot = create_task_loop_snapshot_from_plan(
        "Bitte schrittweise arbeiten: Pruefe den Loop",
        "conv-1",
        thinking_plan={"intent": "Loop pruefen", "suggested_tools": []},
    )

    assert snapshot.current_plan[0] == "Pruefziel festlegen: Loop pruefen"
    assert snapshot.plan_steps[0]["title"] == "Pruefziel festlegen: Loop pruefen"
    assert snapshot.pending_step == "Pruefziel festlegen: Loop pruefen"
