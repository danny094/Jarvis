"""
core.layers.output.prompt.system_prompt
==========================================
System-Prompt-Builder und Message-Array-Konstruktion.

Orchestriert alle Prompt-Sektionen:
  Persona → Anti-Halluzination → Chat-History → Control-Anweisung →
  Memory → Grounding-Rules → Container/Skill-Kontrakte → Warnungen →
  Budget → Sequential-Thinking → Stil → Dialog-Führung
"""
from typing import Any, Dict, List, Optional

from core.persona import get_persona
from core.plan_runtime_bridge import get_policy_final_instruction, get_policy_warnings, get_runtime_tool_results
from core.plan_runtime_bridge import get_runtime_grounding_value
from core.grounding_policy import load_grounding_policy
from core.output_analysis_guard import is_analysis_turn_guard_applicable
from intelligence_modules.prompt_manager import load_prompt
from core.layers.output.prompt.budget import normalize_length_hint, resolve_output_budgets
from core.layers.output.prompt.tool_injection import resolve_tools_for_prompt
from core.layers.output.contracts.container import (
    is_container_query_contract_plan,
    build_container_prompt_rules,
)
from core.layers.output.contracts.skill_catalog import (
    is_skill_catalog_context_plan,
    build_skill_catalog_prompt_rules,
)


def build_system_prompt(
    verified_plan: Dict[str, Any],
    memory_data: str,
    memory_required_but_missing: bool = False,
    needs_chat_history: bool = False,
) -> str:
    """
    Baut den vollständigen System-Prompt für den Output-LLM-Call.

    Sektionen (in Reihenfolge):
      1. Persona-Basis + dynamische Tools
      2. Anti-Halluzination (wenn Memory gesucht aber nicht gefunden)
      3. Chat-History-Hinweis
      4. Control-Layer-Anweisung
      5. Fakten aus dem Gedächtnis
      6. Output-Grounding-Rules (fact_query / tool_usage)
         ODER Analyse-Guard (konzeptionelle Turns)
      7. Container-Prompt-Regeln (wenn Container-Kontrakt-Plan)
      8. Skill-Catalog-Prompt-Regeln (wenn Skill-Catalog-Plan)
      9. Warnungen
     10. Antwort-Budget (hard_cap + soft_target)
     11. Sequential-Thinking-Vorab-Analyse
     12. Stil
     13. Dialog-Führung (dialogue_act + response_tone)
    """
    persona = get_persona()
    prompt_parts = []

    # 1. Persona
    available_tools = resolve_tools_for_prompt(verified_plan)
    dynamic_context = {"tools": available_tools} if available_tools else None
    prompt_parts.append(persona.build_system_prompt(dynamic_context=dynamic_context))

    # 2. Anti-Halluzination
    if memory_required_but_missing:
        prompt_parts.append(load_prompt("contracts", "output_anti_hallucination"))

    # 3. Chat-History
    if needs_chat_history:
        prompt_parts.append(load_prompt("contracts", "output_chat_history"))

    # 4. Control-Layer-Anweisung
    instruction = get_policy_final_instruction(verified_plan)
    if instruction:
        prompt_parts.append(f"\n### ANWEISUNG:\n{instruction}")

    # 5. Memory
    if memory_data:
        prompt_parts.append(f"\n### FAKTEN AUS DEM GEDÄCHTNIS:\n{memory_data}")
        prompt_parts.append("NUTZE diese Fakten!")

    # 6. Grounding-Rules
    is_fact_query = bool(verified_plan.get("is_fact_query", False))
    has_tool_usage = bool(str(get_runtime_tool_results(verified_plan) or "").strip())
    if is_fact_query or has_tool_usage:
        hybrid_mode_line = ""
        if bool(get_runtime_grounding_value(verified_plan, key="hybrid_mode", default=False)):
            hybrid_mode_line = "Antwort darf natürlich formuliert sein, muss aber vollständig evidenzgebunden bleiben."
        prompt_parts.append(
            load_prompt(
                "contracts",
                "output_grounding",
                hybrid_mode_line=hybrid_mode_line,
            )
        )
    elif is_analysis_turn_guard_applicable(
        verified_plan,
        output_cfg=load_grounding_policy().get("output") or {},
        has_tool_usage=has_tool_usage,
        is_fact_query=is_fact_query,
    ):
        prompt_parts.append(load_prompt("contracts", "output_analysis_guard"))

    # 7. Container-Kontrakt
    if is_container_query_contract_plan(verified_plan):
        prompt_parts.extend(build_container_prompt_rules(verified_plan))

    # 8. Skill-Catalog-Kontrakt
    if is_skill_catalog_context_plan(verified_plan):
        prompt_parts.extend(build_skill_catalog_prompt_rules(verified_plan))

    # 9. Warnungen
    warnings = get_policy_warnings(verified_plan)
    if warnings:
        prompt_parts.append("\n### WARNUNGEN:")
        for w in warnings:
            prompt_parts.append(f"- {w}")

    # 10. Antwort-Budget
    response_mode = str(verified_plan.get("_response_mode", "interactive")).lower()
    budgets = resolve_output_budgets(verified_plan)
    soft_target = budgets["soft_target"]
    hard_cap = budgets["hard_cap"]
    length_hint = normalize_length_hint(verified_plan.get("response_length_hint"))
    dialogue_act = str(verified_plan.get("dialogue_act") or "").strip().lower()
    response_tone = str(verified_plan.get("response_tone") or "").strip().lower()
    try:
        tone_confidence = float(verified_plan.get("tone_confidence") or 0.0)
    except Exception:
        tone_confidence = 0.0

    if response_mode != "deep":
        prompt_parts.append(
            load_prompt(
                "contracts",
                "output_budget_interactive",
                soft_target=soft_target,
                hard_cap=hard_cap if hard_cap > 0 else "deaktiviert",
            )
        )
    else:
        prompt_parts.append(
            load_prompt(
                "contracts",
                "output_budget_deep",
                soft_target=soft_target,
                hard_cap=hard_cap if hard_cap > 0 else "deaktiviert",
            )
        )

    # 11. Sequential Thinking
    sequential_result = verified_plan.get("_sequential_result")
    if sequential_result and sequential_result.get("success"):
        prompt_parts.append("\n### VORAB-ANALYSE (Sequential Thinking):")
        full_response = sequential_result.get("full_response", "")
        if full_response and not full_response.startswith("[Ollama Error"):
            prompt_parts.append(full_response[:4000])
        else:
            for step in sequential_result.get("steps", [])[:10]:
                prompt_parts.append(f"**Step {step.get('step', '?')}: {step.get('title', '')}**")
                prompt_parts.append(step.get("thought", "")[:500])
        prompt_parts.append(load_prompt("contracts", "output_sequential_summary"))

    # 12. Stil
    style = verified_plan.get("suggested_response_style", "")
    if style:
        prompt_parts.append(load_prompt("contracts", "output_style", style=style))

    # 13. Dialog-Führung
    if dialogue_act or response_tone:
        prompt_parts.append(load_prompt("contracts", "output_dialogue_header"))
        prompt_parts.append(
            load_prompt(
                "contracts",
                "output_dialogue_metadata",
                dialogue_act=dialogue_act,
                response_tone=response_tone,
                length_hint=length_hint,
                tone_confidence=f"{tone_confidence:.2f}",
            )
        )

        if response_tone == "mirror_user":
            prompt_parts.append(load_prompt("contracts", "output_tone_mirror_user"))
        elif response_tone == "warm":
            prompt_parts.append(load_prompt("contracts", "output_tone_warm"))
        elif response_tone == "formal":
            prompt_parts.append(load_prompt("contracts", "output_tone_formal"))
        else:
            prompt_parts.append(load_prompt("contracts", "output_tone_neutral"))

        if dialogue_act in {"ack", "feedback"} and response_mode != "deep":
            prompt_parts.append(load_prompt("contracts", "output_dialogue_ack_feedback"))
        elif dialogue_act == "smalltalk":
            prompt_parts.append(load_prompt("contracts", "output_dialogue_smalltalk_experience_guard"))
            prompt_parts.append(load_prompt("contracts", "output_dialogue_smalltalk_day_guard"))
        elif length_hint == "short":
            prompt_parts.append(load_prompt("contracts", "output_length_short"))
        elif length_hint == "long":
            prompt_parts.append(load_prompt("contracts", "output_length_long"))

    return "\n".join(prompt_parts)


def build_messages(
    user_text: str,
    verified_plan: Dict[str, Any],
    memory_data: str = "",
    memory_required_but_missing: bool = False,
    chat_history: Optional[list] = None,
) -> List[Dict[str, str]]:
    """
    Baut das Messages-Array für /api/chat.
    Format: [system, ...history, user]
    Chat-History: max. 10 vorherige Turns.
    """
    needs_chat_history = verified_plan.get("needs_chat_history", False)
    system_prompt = build_system_prompt(
        verified_plan, memory_data, memory_required_but_missing,
        needs_chat_history=needs_chat_history,
    )
    messages = [{"role": "system", "content": system_prompt}]

    if chat_history and len(chat_history) > 1:
        history_to_show = chat_history[-11:-1] if len(chat_history) > 11 else chat_history[:-1]
        for msg in history_to_show:
            role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
            if role == "user":
                messages.append({"role": "user", "content": msg.content})
            elif role == "assistant":
                messages.append({"role": "assistant", "content": msg.content})

    messages.append({"role": "user", "content": user_text})
    return messages


def build_full_prompt(
    user_text: str,
    verified_plan: Dict[str, Any],
    memory_data: str = "",
    memory_required_but_missing: bool = False,
    chat_history: Optional[list] = None,
) -> str:
    """
    Legacy-Prompt für /api/generate (Ollama sync-Stream).
    Format: system prompt plus optional history, current user block, and answer marker.
    """
    needs_chat_history = verified_plan.get("needs_chat_history", False)
    system_prompt = build_system_prompt(
        verified_plan, memory_data, memory_required_but_missing,
        needs_chat_history=needs_chat_history,
    )
    prompt_parts = [system_prompt]

    if chat_history and len(chat_history) > 1:
        prompt_parts.append(load_prompt("contracts", "output_legacy_history_header"))
        history_to_show = chat_history[-11:-1] if len(chat_history) > 11 else chat_history[:-1]
        for msg in history_to_show:
            role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
            if role == "user":
                prompt_parts.append(f"USER: {msg.content}")
            elif role == "assistant":
                prompt_parts.append(f"ASSISTANT: {msg.content}")

    prompt_parts.append(load_prompt("contracts", "output_legacy_user_block", user_text=user_text))
    prompt_parts.append(load_prompt("contracts", "output_legacy_answer_header"))
    return "\n".join(prompt_parts)
