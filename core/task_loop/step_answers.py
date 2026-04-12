from __future__ import annotations

from typing import Any, Dict, List


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _title_focus(title: str) -> str:
    if ":" not in title:
        return _text(title)
    return _text(title.split(":", 1)[1])


def _objective(meta: Dict[str, Any], step: str) -> str:
    objective = _text(meta.get("objective"))
    return (objective or _title_focus(step) or _text(step)).rstrip(" .!?:;")


def _prior_context(completed_steps: List[str]) -> str:
    if not completed_steps:
        return "Es gibt noch keinen vorherigen Loop-Schritt."
    cleaned = [_text(step).rstrip(" .!?:;") for step in completed_steps]
    return "Bisher abgeschlossen: " + "; ".join(cleaned) + "."


def _validation_answer(
    step_index: int,
    step: str,
    meta: Dict[str, Any],
    completed_steps: List[str],
) -> str:
    objective = _objective(meta, step)
    if step_index == 1:
        return (
            f"Pruefziel: {objective}. Erfolgskriterium: Der Loop liefert einen "
            "sichtbaren Plan, erzeugt nachvollziehbare Zwischenstaende, reflektiert "
            "Stopbedingungen und bleibt im Chat-only Rahmen ohne Tools, Shell oder Writes."
        )
    if step_index == 2:
        return (
            "Beobachtbare Kriterien: Planpunkte muessen zur Anfrage passen; jeder "
            "Zwischenstand muss einen konkreten Befund statt nur eine Statusfloskel "
            "enthalten; riskante Folgepfade muessen vor Ausfuehrung stoppen."
        )
    if step_index == 3:
        return (
            f"Befund: Der aktuelle Pfad bleibt sicher, weil keine externe Aktion "
            f"ausgefuehrt wird. {_prior_context(completed_steps)} Stop wuerde bei "
            "riskantem Tool-/Shell-/Write-Pfad, unklarem Ziel, fehlendem Fortschritt, "
            "Wiederholung oder Step-/Error-Limit greifen."
        )
    return (
        "Zusammenfassung: Die Pruefung ist als Chat-only Zwischenstand abgeschlossen. "
        "Naechster Produktpfad: die Zwischenstaende weiter von reinen Templates loesen "
        "und spaeter echte Tool-/Shell-Schritte erst hinter Risk-Gates aktivieren."
    )


def _implementation_answer(
    step_index: int,
    step: str,
    meta: Dict[str, Any],
    completed_steps: List[str],
) -> str:
    objective = _objective(meta, step)
    if step_index == 1:
        return (
            f"Zielbild: {objective}. Der sichere erste Schnitt ist ein kleiner, "
            "beobachtbarer Chat-Loop, der Zustand, Plan, Zwischenstand und Stopgrund "
            "sauber trennt."
        )
    if step_index == 2:
        return (
            "Umsetzungsschnitt: Planer, Runner, Reflection und Gates bleiben getrennt. "
            "Der naechste sichere Schritt darf nur Chat-Zustand und sichtbare Antwort "
            "veraendern, keine Tools oder Shell ausfuehren."
        )
    if step_index == 3:
        return (
            f"Gate-Bewertung: {_prior_context(completed_steps)} Automatisch weiter "
            "geht nur, solange der Schritt safe ist. Bei User-Entscheidung, riskantem "
            "Tool, Write, Shell, Wiederholung oder Fehlerlimit wird pausiert."
        )
    return (
        "Naechster Implementierungsschnitt: echte Ausfuehrungssignale und bessere "
        "Plan-Revisionen anbinden, ohne den Orchestrator-Monolithen weiter wachsen "
        "zu lassen."
    )


def _analysis_answer(
    step_index: int,
    step: str,
    meta: Dict[str, Any],
    completed_steps: List[str],
) -> str:
    objective = _objective(meta, step)
    if step_index == 1:
        return (
            f"Fragestellung: {objective}. Die Antwort muss klaeren, was belastbar aus "
            "dem aktuellen Chat-Kontext folgt und wo der Loop stoppen oder nachfragen "
            "muss."
        )
    if step_index == 2:
        return (
            "Einflussfaktoren: expliziter Multistep-Start, Planqualitaet, sichtbare "
            "Zwischenstaende, Reflection, Risk-Gates, Progress-Erkennung und harte "
            "Limits fuer Steps, Errors und Wiederholung."
        )
    if step_index == 3:
        return (
            f"Unsicherheiten: {_prior_context(completed_steps)} Ohne externe Pruefung "
            "bleibt der Befund auf Chat-Kontext begrenzt. Stoppen ist korrekt, wenn "
            "Kontext fehlt, Risiko entsteht oder kein konkreter naechster Schritt "
            "ableitbar ist."
        )
    return (
        "Zwischenfazit: Der sichere Analysepfad ist abgeschlossen. Der naechste "
        "sinnvolle Schritt ist, die erkannte Luecke gezielt zu beheben statt den Loop "
        "blind weiterlaufen zu lassen."
    )


def _default_answer(
    step_index: int,
    step: str,
    meta: Dict[str, Any],
    completed_steps: List[str],
) -> str:
    objective = _objective(meta, step)
    if step_index == 1:
        return (
            f"Aufgabe: {objective}. Erfolg heisst, dass der naechste Schritt konkret, "
            "sicher und fuer den User nachvollziehbar ist."
        )
    if step_index == 2:
        return (
            "Naechster sicherer Schritt: im Chat bleiben, den kleinsten sinnvollen "
            "Fortschritt benennen und externe Nebenwirkungen ausklammern."
        )
    if step_index == 3:
        return (
            f"Stoppruefung: {_prior_context(completed_steps)} Kein riskanter Pfad wird "
            "automatisch ausgefuehrt; bei Unsicherheit oder Wiederholung wird pausiert."
        )
    return (
        "Status: Die Aufgabe ist im sicheren Chat-Rahmen sortiert. Der naechste "
        "Pfad ist klar genug, um gezielt weiterzuplanen oder bei Bedarf nachzufragen."
    )


def answer_for_chat_step(
    step_index: int,
    step: str,
    meta: Dict[str, Any],
    completed_steps: List[str],
) -> str:
    kind = _text(meta.get("task_kind")) or "default"
    if kind == "validation":
        return _validation_answer(step_index, step, meta, completed_steps)
    if kind == "implementation":
        return _implementation_answer(step_index, step, meta, completed_steps)
    if kind == "analysis":
        return _analysis_answer(step_index, step, meta, completed_steps)
    return _default_answer(step_index, step, meta, completed_steps)
