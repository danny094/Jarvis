from __future__ import annotations

import unicodedata
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any, Dict, List, Optional

from core.loop_trace import normalize_internal_loop_analysis_plan
from core.task_loop.contracts import RiskLevel, TaskLoopSnapshot


TASK_LOOP_START_MARKERS = (
    "task-loop",
    "task loop",
    "taskloop",
    "im task-loop modus",
    "im task loop modus",
    "im multistep modus",
    "multistep modus",
    "multistep",
    "multi-step",
    "mehrschritt",
    "schrittweise",
    "schritt fuer schritt",
    "schritt fur schritt",
    "step by step",
    "planungsmodus",
    "plan und dann",
    "plane und fuehre",
)


@dataclass(frozen=True)
class TaskLoopStep:
    step_id: str
    title: str
    goal: str
    done_criteria: str
    risk_level: RiskLevel = RiskLevel.SAFE
    requires_user: bool = False
    suggested_tools: List[str] = None
    task_kind: str = "default"
    objective: str = ""

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["risk_level"] = self.risk_level.value
        out["suggested_tools"] = list(self.suggested_tools or [])
        return out


def clean_task_loop_objective(user_text: str) -> str:
    objective = " ".join(str(user_text or "").strip().split())
    objective = objective.removeprefix("Bitte ").strip()
    for marker in TASK_LOOP_START_MARKERS:
        lower = objective.lower()
        if lower.startswith(marker + ":"):
            objective = objective[len(marker) + 1:].strip()
            break
        if lower.startswith(marker + " "):
            objective = objective[len(marker):].strip(" :")
            break
    objective = objective.removeprefix("Bitte ").strip()
    lower = objective.lower()
    for prefix in ("einen plan machen:", "einen plan erstellen:", "arbeiten:"):
        if lower.startswith(prefix):
            objective = objective[len(prefix):].strip()
            break
    return objective or "Aufgabe"


def _clip(value: Any, limit: int = 120) -> str:
    text = " ".join(str(value or "").strip().split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _keyword_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.lower().split())


def _has_any_keyword(value: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in value for keyword in keywords)


def _is_fallback_text(value: Any) -> bool:
    text = _keyword_text(value)
    if not text:
        return False
    return _has_any_keyword(
        text,
        (
            "fallback",
            "analyse fehlgeschlagen",
            "analysis failed",
            "unknown",
            "nicht analysiert",
        ),
    )


def _clean_reasoning(value: Any) -> str:
    reasoning = _clip(value, 160)
    if _is_fallback_text(reasoning):
        return ""
    return reasoning


def _is_fallback_thinking_plan(thinking_plan: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(thinking_plan, dict) or not thinking_plan:
        return True
    raw_intent = str(thinking_plan.get("intent") or "").strip()
    reasoning = str(thinking_plan.get("reasoning") or "").strip()
    intent_lower = raw_intent.lower()
    if (
        raw_intent
        and intent_lower not in {"unknown", "fallback"}
        and not _is_fallback_text(raw_intent)
    ):
        return False
    return not reasoning or _is_fallback_text(reasoning)


def _risk_from_thinking_plan(thinking_plan: Optional[Dict[str, Any]]) -> RiskLevel:
    plan = thinking_plan if isinstance(thinking_plan, dict) else {}
    risk = str(plan.get("hallucination_risk") or "").strip().lower()
    suggested_tools = [
        str(item or "").strip() for item in plan.get("suggested_tools") or []
    ]
    write_like_tools = {
        "memory_save",
        "home_write",
        "request_container",
        "stop_container",
        "exec_in_container",
        "create_skill",
        "autonomous_skill_task",
    }
    if write_like_tools.intersection(set(suggested_tools)):
        return RiskLevel.NEEDS_CONFIRMATION
    if risk == "high":
        return RiskLevel.NEEDS_CONFIRMATION
    return RiskLevel.SAFE


def _task_kind(objective: str, intent: str) -> str:
    text = _keyword_text(f"{objective} {intent}")
    if _has_any_keyword(
        text,
        (
            "pruef",
            "pruf",
            "check",
            "validier",
            "test",
            "verifizier",
            "review",
            "bewert",
        ),
    ):
        return "validation"
    if _has_any_keyword(
        text,
        (
            "implement",
            "umsetz",
            "bau",
            "fix",
            "verbesser",
            "erweiter",
            "aender",
            "ander",
            "update",
            "erstelle",
        ),
    ):
        return "implementation"
    if _has_any_keyword(
        text,
        (
            "analys",
            "untersuch",
            "erklaer",
            "warum",
            "einschaetz",
            "vergleich",
            "finde heraus",
        ),
    ):
        return "analysis"
    return "default"


def _base_steps_for_kind(
    kind: str,
    *,
    intent: str,
    objective: str,
    risk_level: RiskLevel,
    suggested_tools: List[str],
) -> List[TaskLoopStep]:
    focus = _clip(intent, 120)
    objective_text = _keyword_text(objective)
    goal_subject = (
        intent
        if objective_text in {"arbeiten", "bearbeiten", "aufgabe"}
        or objective_text.startswith("schrittweise ")
        else objective
    )
    clipped_subject = _clip(goal_subject, 180)
    if kind == "validation":
        specs = (
            (
                f"Pruefziel festlegen: {focus}",
                f"Festlegen, welche beobachtbare Aussage geprueft wird: {clipped_subject}",
                "Pruefziel und Erfolgskriterium sind als Chat-Kontext formuliert.",
                RiskLevel.SAFE,
            ),
            (
                "Beobachtbare Kriterien definieren",
                "Konkrete Kriterien nennen, an denen der sichere Zwischenstand erkennbar ist.",
                "Die Pruefung hat sichtbare Kriterien statt nur eine generische Aussage.",
                RiskLevel.SAFE,
            ),
            (
                "Befund gegen Stopbedingungen bewerten",
                "Den aktuellen Befund gegen Risiko, Wiederholung, fehlenden Fortschritt und Unklarheit pruefen.",
                "Stop-/Continue-Entscheidung ist mit einem konkreten Befund begruendet.",
                risk_level,
            ),
            (
                "Befund und naechsten Produktpfad zusammenfassen",
                "Die sicheren Erkenntnisse knapp zusammenfassen und den naechsten sinnvollen Produktpfad nennen.",
                "User sieht Befund, Status und naechsten sicheren Pfad.",
                RiskLevel.SAFE,
            ),
        )
    elif kind == "implementation":
        specs = (
            (
                f"Zielbild konkretisieren: {focus}",
                f"Festlegen, welches konkrete Verhalten oder Artefakt entstehen soll: {clipped_subject}",
                "Zielbild und Erfolgskriterium sind fuer die Umsetzung greifbar.",
                RiskLevel.SAFE,
            ),
            (
                "Umsetzungsschritte trennen",
                "Die Arbeit in kleine, sichere Chat-Schritte schneiden und riskante Aktionen ausklammern.",
                "Der naechste Umsetzungsschnitt ist klein genug fuer kontrolliertes Weiterarbeiten.",
                RiskLevel.SAFE,
            ),
            (
                "Risiko- und Stop-Gates pruefen",
                "Pruefen, ob der naechste Umsetzungsschritt User-Freigabe, Tools, Shell oder Writes braucht.",
                "Riskante Pfade sind markiert und werden nicht automatisch ausgefuehrt.",
                risk_level,
            ),
            (
                "Naechsten Implementierungsschnitt festlegen",
                "Den naechsten sicheren Umsetzungsschnitt und den Stopgrund bei Blockade benennen.",
                "User sieht, was als naechstes sicher umgesetzt werden kann.",
                RiskLevel.SAFE,
            ),
        )
    elif kind == "analysis":
        specs = (
            (
                f"Fragestellung eingrenzen: {focus}",
                f"Die eigentliche Analysefrage aus der Anfrage herausarbeiten: {clipped_subject}",
                "Fragestellung und gewuenschtes Ergebnis sind klar formuliert.",
                RiskLevel.SAFE,
            ),
            (
                "Einflussfaktoren sammeln",
                "Relevante Faktoren, Annahmen und Abhaengigkeiten fuer die Antwort sammeln.",
                "Die Analyse stuetzt sich auf konkrete Faktoren statt auf eine leere Zusammenfassung.",
                RiskLevel.SAFE,
            ),
            (
                "Unsicherheiten und Stopgruende pruefen",
                "Pruefen, ob Unsicherheit, fehlender Kontext, Risiko oder fehlender Fortschritt einen Stop braucht.",
                "Offene Unsicherheiten sind benannt und die Continue-Entscheidung ist begruendet.",
                risk_level,
            ),
            (
                "Zwischenfazit mit naechstem Schritt formulieren",
                "Das belastbare Zwischenfazit und den naechsten sinnvollen Schritt nennen.",
                "User sieht Fazit, Restunsicherheit und Folgepfad.",
                RiskLevel.SAFE,
            ),
        )
    else:
        specs = (
            (
                f"Aufgabe konkretisieren: {focus}",
                f"Festhalten, was erreicht werden soll: {clipped_subject}",
                "Ziel und Erfolgskriterium sind als Chat-Kontext formuliert.",
                RiskLevel.SAFE,
            ),
            (
                "Naechsten sicheren Schritt bestimmen",
                "Den naechsten konkreten Schritt bestimmen, der ohne externe Nebenwirkungen moeglich ist.",
                "Der naechste Schritt ist sicher, konkret und nicht nur eine Wiederholung.",
                RiskLevel.SAFE,
            ),
            (
                "Risiko und Stopbedingungen pruefen",
                "Loop-Gates gegen Risiko, Wiederholung, fehlenden Fortschritt und unklare Absicht pruefen.",
                "Stop-/Continue-Entscheidung ist begruendet.",
                risk_level,
            ),
            (
                "Zwischenstand und Folgepfad zusammenfassen",
                "Den sicheren Zwischenstand zusammenfassen und den naechsten sinnvollen Produktpfad nennen.",
                "User sieht Status, Abschluss und naechsten sicheren Pfad.",
                RiskLevel.SAFE,
            ),
        )

    steps: List[TaskLoopStep] = []
    for index, (title, goal, done_criteria, step_risk) in enumerate(specs, start=1):
        steps.append(
            TaskLoopStep(
                step_id=f"step-{index}",
                title=title,
                goal=goal,
                done_criteria=done_criteria,
                risk_level=step_risk,
                requires_user=step_risk is not RiskLevel.SAFE,
                suggested_tools=suggested_tools if step_risk is not RiskLevel.SAFE else [],
                task_kind=kind,
                objective=goal_subject,
            )
        )
    return steps


def build_task_loop_steps(
    user_text: str,
    *,
    thinking_plan: Optional[Dict[str, Any]] = None,
    max_steps: int = 4,
) -> List[TaskLoopStep]:
    plan = dict(thinking_plan) if isinstance(thinking_plan, dict) else {}
    plan = normalize_internal_loop_analysis_plan(
        plan,
        user_text=user_text,
        contains_explicit_tool_intent=False,
        has_memory_recall_signal=False,
    )
    objective = clean_task_loop_objective(user_text)
    usable_plan = {} if _is_fallback_thinking_plan(plan) else plan
    raw_intent = str(usable_plan.get("intent") or "").strip()
    intent = _clip(raw_intent if raw_intent and raw_intent != "unknown" else objective)
    reasoning = _clean_reasoning(usable_plan.get("reasoning"))
    risk_level = _risk_from_thinking_plan(plan)
    suggested_tools = [
        str(item or "").strip()
        for item in plan.get("suggested_tools") or []
        if str(item or "").strip()
    ]
    raw_complexity = str(plan.get("sequential_complexity") or "")
    complexity = int(raw_complexity) if raw_complexity.isdigit() else 0

    steps = _base_steps_for_kind(
        _task_kind(objective, intent),
        intent=intent,
        objective=objective,
        risk_level=risk_level,
        suggested_tools=suggested_tools,
    )

    if reasoning:
        steps[1] = TaskLoopStep(
            step_id=steps[1].step_id,
            title=steps[1].title,
            goal=f"{steps[1].goal} Planhinweis: {reasoning}",
            done_criteria=steps[1].done_criteria,
            risk_level=steps[1].risk_level,
            requires_user=steps[1].requires_user,
            suggested_tools=steps[1].suggested_tools,
            task_kind=steps[1].task_kind,
            objective=steps[1].objective,
        )

    if complexity >= 7 and max_steps >= 4:
        steps[2] = TaskLoopStep(
            step_id=steps[2].step_id,
            title="Komplexitaet und Teilziele pruefen",
            goal="Pruefen, ob der Plan wegen hoher Komplexitaet spaeter tieferes Planning braucht.",
            done_criteria="Komplexitaet ist sichtbar eingeordnet, ohne Tools auszufuehren.",
            risk_level=steps[2].risk_level,
            requires_user=steps[2].requires_user,
            suggested_tools=steps[2].suggested_tools,
            task_kind=steps[2].task_kind,
            objective=steps[2].objective,
        )

    return steps[: max(1, max_steps)]


def create_task_loop_snapshot_from_plan(
    user_text: str,
    conversation_id: str,
    *,
    thinking_plan: Optional[Dict[str, Any]] = None,
    max_steps: int = 4,
) -> TaskLoopSnapshot:
    seed = f"{conversation_id}:{user_text}".encode("utf-8", errors="ignore")
    suffix = sha256(seed).hexdigest()[:12]
    steps = build_task_loop_steps(user_text, thinking_plan=thinking_plan, max_steps=max_steps)
    plan_titles = [step.title for step in steps]
    first = plan_titles[0] if plan_titles else ""
    return TaskLoopSnapshot(
        objective_id=f"obj-{suffix}",
        conversation_id=conversation_id or "global",
        plan_id=f"plan-{suffix}",
        current_plan=plan_titles,
        plan_steps=[step.to_dict() for step in steps],
        pending_step=first,
        risk_level=RiskLevel.SAFE,
    )
