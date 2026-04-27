from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Dict, List, Optional

from core.loop_trace import normalize_internal_loop_analysis_plan
from core.task_loop.capabilities.container.context import build_container_context
from core.task_loop.capabilities.container.flow import build_container_step_blueprints
from core.task_loop.capability_policy import (
    capability_type_from_tools,
    requested_capability_from_tools,
    scoped_tools_for_step,
)
from core.task_loop.contracts import RiskLevel, TaskLoopStepType
from core.task_loop.planner.objective import (
    _clean_reasoning,
    _clip,
    _is_fallback_thinking_plan,
    _keyword_text,
    _risk_from_thinking_plan,
    _task_kind,
    clean_task_loop_objective,
)
from core.task_loop.planner.specs import _step3_risk_for_container, _tool_focused_specs
from core.task_loop.tool_step_policy import (
    infer_planned_step_type,
    step_tools_for_spec,
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
    step_type: TaskLoopStepType = TaskLoopStepType.ANALYSIS
    requested_capability: Dict[str, Any] = None
    capability_context: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["risk_level"] = self.risk_level.value
        out["suggested_tools"] = list(self.suggested_tools or [])
        out["step_type"] = self.step_type.value
        out["requested_capability"] = dict(self.requested_capability or {})
        out["capability_context"] = dict(self.capability_context or {})
        return out


def _base_steps_for_kind(
    kind: str,
    *,
    user_text: str,
    intent: str,
    objective: str,
    risk_level: RiskLevel,
    suggested_tools: List[str],
    capability_context: Optional[Dict[str, Any]] = None,
    thinking_plan: Optional[Dict[str, Any]] = None,
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
    if capability_type_from_tools(suggested_tools) == "container_manager":
        container_capability_context = build_container_context(
            user_text,
            thinking_plan=thinking_plan or {"intent": intent, "suggested_tools": suggested_tools},
            selected_tools=suggested_tools,
            existing_context=capability_context,
        )
        container_blueprints = build_container_step_blueprints(
            intent=focus,
            objective=clipped_subject,
            risk_level=_step3_risk_for_container(suggested_tools),
            suggested_tools=suggested_tools,
            capability_context=container_capability_context,
        )
        if container_blueprints:
            return [
                TaskLoopStep(
                    step_id=f"step-{index}",
                    title=str(blueprint["title"]),
                    goal=str(blueprint["goal"]),
                    done_criteria=str(blueprint["done_criteria"]),
                    risk_level=blueprint["risk_level"],
                    requires_user=blueprint["risk_level"] is not RiskLevel.SAFE,
                    suggested_tools=list(blueprint.get("suggested_tools") or []),
                    task_kind=kind,
                    objective=goal_subject,
                    step_type=blueprint["step_type"],
                    requested_capability=dict(blueprint.get("requested_capability") or {}),
                    capability_context=dict(blueprint.get("capability_context") or {}),
                )
                for index, blueprint in enumerate(container_blueprints, start=1)
            ]
    if suggested_tools:
        specs = _tool_focused_specs(
            intent=intent,
            objective=goal_subject,
            risk_level=risk_level,
            suggested_tools=suggested_tools,
        )
    elif kind == "validation":
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
    total_steps = len(specs)
    for index, (title, goal, done_criteria, step_risk) in enumerate(specs, start=1):
        step_tools = step_tools_for_spec(
            index=index,
            total_steps=total_steps,
            step_risk=step_risk,
            suggested_tools=suggested_tools,
        )
        step_type = infer_planned_step_type(
            title,
            index=index,
            total_steps=total_steps,
            step_risk=step_risk,
            suggested_tools=step_tools,
        )
        step_tools = scoped_tools_for_step(
            step_tools,
            step_type=step_type,
        )
        steps.append(
            TaskLoopStep(
                step_id=f"step-{index}",
                title=title,
                goal=goal,
                done_criteria=done_criteria,
                risk_level=step_risk,
                requires_user=step_risk is not RiskLevel.SAFE,
                suggested_tools=step_tools,
                task_kind=kind,
                objective=goal_subject,
                step_type=step_type,
                requested_capability=requested_capability_from_tools(step_tools),
                capability_context=dict(capability_context or {})
                if capability_type_from_tools(suggested_tools) == "container_manager"
                else {},
            )
        )
    return steps


def build_task_loop_steps(
    user_text: str,
    *,
    thinking_plan: Optional[Dict[str, Any]] = None,
    max_steps: int = 5,
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
    capability_context = plan.get("_container_capability_context")

    steps = _base_steps_for_kind(
        _task_kind(objective, intent),
        user_text=user_text,
        intent=intent,
        objective=objective,
        risk_level=risk_level,
        suggested_tools=suggested_tools,
        capability_context=capability_context if isinstance(capability_context, dict) else None,
        thinking_plan=plan,
    )

    if reasoning:
        steps[1] = replace(
            steps[1],
            goal=f"{steps[1].goal} Planhinweis: {reasoning}",
        )

    if (
        complexity >= 7
        and max_steps >= 4
        and steps[2].step_type not in {TaskLoopStepType.TOOL_REQUEST, TaskLoopStepType.TOOL_EXECUTION}
    ):
        steps[2] = replace(
            steps[2],
            title="Komplexitaet und Teilziele pruefen",
            goal="Pruefen, ob der Plan wegen hoher Komplexitaet spaeter tieferes Planning braucht.",
            done_criteria="Komplexitaet ist sichtbar eingeordnet, ohne Tools auszufuehren.",
        )

    return steps[: max(1, max_steps)]


__all__ = [
    "TaskLoopStep",
    "_base_steps_for_kind",
    "build_task_loop_steps",
]
