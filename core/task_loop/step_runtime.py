from __future__ import annotations
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Callable, Dict, List

from core.control_contract import ControlDecision, persist_control_decision
from core.task_loop.contracts import TaskLoopSnapshot


@dataclass(frozen=True)
class TaskLoopStepRuntimeResult:
    visible_text: str
    control_decision: ControlDecision
    verified_plan: Dict[str, Any]
    used_fallback: bool = False


@dataclass(frozen=True)
class PreparedTaskLoopStepRuntime:
    prompt: str
    fallback_text: str
    control_decision: ControlDecision
    verified_plan: Dict[str, Any]


def _clip(text: Any, limit: int = 400) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


def build_task_loop_step_prompt(
    step_title: str,
    step_meta: Dict[str, Any],
    snapshot: TaskLoopSnapshot,
) -> str:
    objective = str(step_meta.get("objective") or "").strip() or snapshot.pending_step.strip() or "Aufgabe"
    goal = str(step_meta.get("goal") or "").strip()
    done_criteria = str(step_meta.get("done_criteria") or "").strip()
    completed = [str(item or "").strip() for item in snapshot.completed_steps if str(item or "").strip()]
    completed_text = ", ".join(completed) if completed else "keiner"
    current_step_index = int(snapshot.step_index or 0) + 1
    total_steps = max(len(snapshot.current_plan), current_step_index)

    return (
        f"Task-Loop Schritt {current_step_index}/{total_steps}\n\n"
        f"Aufgabe: {objective}\n"
        f"Aktueller Schritt: {step_title}\n"
        f"Ziel dieses Schritts: {goal or 'Konkreten Zwischenstand fuer diesen Schritt liefern.'}\n"
        f"Erfolgskriterium: {done_criteria or 'Der Schritt liefert einen klaren, belastbaren Zwischenstand.'}\n"
        f"Bisherige Schritte: {completed_text}\n\n"
        "Arbeite im Chat-only Analysemodus.\n"
        "Keine Tools wurden ausgefuehrt.\n"
        "Behaupte keine Runtime-, Memory-, Container-, Blueprint- oder Systemstatus-Fakten, "
        "wenn sie nicht im aktuellen Chat-Kontext belastbar sind.\n"
        "Antworte konkret und kurz in 2-4 Saetzen.\n"
        "Formuliere einen sichtbaren Zwischenstand fuer den User mit:\n"
        "- konkretem Befund dieses Schritts\n"
        "- verbleibender Unsicherheit\n"
        "- naechstem sinnvollen Schritt\n"
    )


def build_task_loop_step_plan(
    step_title: str,
    step_meta: Dict[str, Any],
    snapshot: TaskLoopSnapshot,
) -> Dict[str, Any]:
    objective = str(step_meta.get("objective") or "").strip() or snapshot.pending_step.strip() or "Aufgabe"
    return {
        "intent": f"{step_title}: {objective}",
        "needs_sequential_thinking": True,
        "_loop_trace_mode": "internal_loop_analysis",
        "_task_loop_step_runtime": True,
        "_response_mode": "interactive",
        "response_length_hint": "short",
        "_output_time_budget_s": 8.0,
        "needs_memory": False,
        "memory_keys": [],
        "needs_chat_history": False,
        "is_fact_query": False,
        "hallucination_risk": "low",
        "step_title": step_title,
        "step_goal": str(step_meta.get("goal") or "").strip(),
        "step_done_criteria": str(step_meta.get("done_criteria") or "").strip(),
    }


async def execute_task_loop_step(
    step_title: str,
    step_meta: Dict[str, Any],
    snapshot: TaskLoopSnapshot,
    *,
    control_layer: Any,
    output_layer: Any,
    fallback_fn: Callable[[int, str, Dict[str, Any], List[str]], str],
) -> TaskLoopStepRuntimeResult:
    prepared = await prepare_task_loop_step_runtime(
        step_title,
        step_meta,
        snapshot,
        control_layer=control_layer,
        fallback_fn=fallback_fn,
    )
    if output_layer is None:
        return TaskLoopStepRuntimeResult(
            visible_text=_clip(prepared.fallback_text),
            control_decision=prepared.control_decision,
            verified_plan=prepared.verified_plan,
            used_fallback=True,
        )

    try:
        chunks: List[str] = []
        async for chunk in stream_task_loop_step_output(prepared, output_layer=output_layer):
            if chunk:
                chunks.append(str(chunk))
        visible_text = _clip("".join(chunks).strip())
        if not visible_text:
            raise ValueError("empty_step_output")
        return TaskLoopStepRuntimeResult(
            visible_text=visible_text,
            control_decision=prepared.control_decision,
            verified_plan=prepared.verified_plan,
            used_fallback=False,
        )
    except Exception:
        return TaskLoopStepRuntimeResult(
            visible_text=_clip(prepared.fallback_text),
            control_decision=prepared.control_decision,
            verified_plan=prepared.verified_plan,
            used_fallback=True,
        )


async def prepare_task_loop_step_runtime(
    step_title: str,
    step_meta: Dict[str, Any],
    snapshot: TaskLoopSnapshot,
    *,
    control_layer: Any,
    fallback_fn: Callable[[int, str, Dict[str, Any], List[str]], str],
) -> PreparedTaskLoopStepRuntime:
    fallback_text = fallback_fn(
        int(snapshot.step_index or 0) + 1,
        step_title,
        step_meta,
        list(snapshot.completed_steps),
    )
    step_plan = build_task_loop_step_plan(step_title, step_meta, snapshot)
    prompt = build_task_loop_step_prompt(step_title, step_meta, snapshot)

    verification: Dict[str, Any] = {"approved": True, "decision_class": "allow"}
    if control_layer is not None:
        try:
            verification = await control_layer.verify(
                prompt,
                step_plan,
                retrieved_memory="",
                response_mode="interactive",
            )
        except Exception:
            verification = {"approved": True, "decision_class": "allow"}

    control_decision = ControlDecision.from_verification(
        verification,
        default_approved=True,
    )
    persist_control_decision(step_plan, control_decision)
    return PreparedTaskLoopStepRuntime(
        prompt=prompt,
        fallback_text=fallback_text,
        control_decision=control_decision,
        verified_plan=step_plan,
    )


async def stream_task_loop_step_output(
    prepared: PreparedTaskLoopStepRuntime,
    *,
    output_layer: Any,
) -> AsyncGenerator[str, None]:
    # The OutputLayer already enforces the per-step timeout via
    # verified_plan["_output_time_budget_s"]. A second outer timeout here can
    # cancel an active token stream mid-response and tear down the HTTP stream.
    async for chunk in output_layer.generate_stream(
        user_text=prepared.prompt,
        verified_plan=prepared.verified_plan,
        memory_data="",
        control_decision=prepared.control_decision,
        execution_result=prepared.verified_plan.get("_execution_result"),
    ):
        if chunk:
            yield str(chunk)
