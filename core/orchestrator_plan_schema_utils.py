from typing import Any, Callable, Dict, List

from core.loop_trace import normalize_internal_loop_analysis_plan


_ALLOWED_RESOLUTION_STRATEGIES = {
    "container_inventory",
    "container_blueprint_catalog",
    "container_state_binding",
    "container_request",
    "active_container_capability",
    "home_container_info",
    "skill_catalog_context",
}

_ALLOWED_SKILL_CATALOG_HINTS = {
    "runtime_skills",
    "draft_skills",
    "tools_vs_skills",
    "session_skills",
    "overview",
    "fact_then_followup",
    "answering_rules",
    "skill_taxonomy",
}


def _contains_any(text: str, markers: List[str]) -> bool:
    return any(marker in text for marker in markers)


def _tool_name_list(raw_tools: Any) -> List[str]:
    out: List[str] = []
    for item in list(raw_tools or []):
        if isinstance(item, dict):
            name = str(item.get("tool") or item.get("name") or "").strip().lower()
        else:
            name = str(item or "").strip().lower()
        if name:
            out.append(name)
    return out


def _has_explicit_draft_skill_signal(normalized_user_text: str) -> bool:
    return _contains_any(
        normalized_user_text,
        [
            "draft skills",
            "draft-skill",
            "entwurf",
            "nicht aktiv",
            "noch nicht aktiv",
        ],
    )


def _has_container_request_signal(normalized_user_text: str) -> bool:
    return _contains_any(
        normalized_user_text,
        [
            "starte container",
            "start container",
            "container starten",
            "deploy",
            "brauche sandbox",
            "brauche container",
            "starte einen container",
            "starte einen python-container",
            "starte einen node-container",
            "python sandbox",
            "node sandbox",
            "python-container",
            "node-container",
        ],
    )


def _has_container_blueprint_signal(normalized_user_text: str) -> bool:
    return _contains_any(
        normalized_user_text,
        [
            "blueprint",
            "blueprints",
            "container blueprint",
            "container blueprints",
            "container-typ",
            "container typen",
            "containertypen",
            "welche container kann ich starten",
            "welche container koennte ich starten",
            "welche sandboxes stehen zur auswahl",
            "welche sandboxes gibt es",
            "welche sandboxes",
            "welche container sind startbar",
            "installierbare blueprints",
            "installable blueprints",
            "startbare container",
            "user selectable containers",
        ],
    )


def _has_container_state_signal(normalized_user_text: str) -> bool:
    return _contains_any(
        normalized_user_text,
        [
            "welcher container ist aktiv",
            "welcher container ist gerade aktiv",
            "welcher container laeuft gerade fuer mich",
            "welcher container läuft gerade für mich",
            "get_active_container",
            "get_active_container_context",
            "current container binding",
            "current container",
            "active container",
            "aktiver container",
            "aktueller container",
            "session container",
            "container binding",
            "container gebunden",
            "woran ist",
            "auf welchen container",
            "runtime status",
            "container runtime status",
        ],
    )


def _has_container_inventory_signal(normalized_user_text: str) -> bool:
    return _contains_any(
        normalized_user_text,
        [
            "welche container hast du",
            "welche container gibt es gerade",
            "welche container laufen",
            "welche container sind installiert",
            "welche container sind gestoppt",
            "list_running_containers",
            "list_stopped_containers",
            "list_attached_containers",
            "list_active_session_containers",
            "list_recently_used_containers",
            "running containers",
            "stopped containers",
            "installed containers",
            "container liste",
            "container list",
        ],
    )


def _infer_skill_strategy_hints(normalized_user_text: str, suggested_tools: List[str]) -> List[str]:
    hints: List[str] = []

    def _add(value: str) -> None:
        if value and value not in hints:
            hints.append(value)

    _add("skill_taxonomy")
    _add("answering_rules")

    has_generic_skill_inventory_question = _contains_any(
        normalized_user_text,
        [
            "welche skills hast",
            "welche skills gibt es",
            "welche skills stehen",
            "welche skills stehen dir",
            "verfuegbare skills",
            "verfügbare skills",
            "skills zur verfuegung",
            "skills zur verfügung",
            "skills zu verfuegung",
            "skills zu verfügung",
            "dir stehen skills",
            "was fuer skills",
            "was für skills",
        ],
    )
    has_followup_brainstorm_signal = _contains_any(
        normalized_user_text,
        [
            "wuenschen",
            "wünschen",
            "wuensch",
            "wünsch",
            "wuerdest du dir",
            "würdest du dir",
            "als naechstes",
            "als nächstes",
            "haettest du gerne",
            "hättest du gerne",
            "welche skills haettest du gerne",
            "welche skills hättest du gerne",
            "wuenschst du dir",
            "wünschst du dir",
            "welche skills fehlen",
            "welche fehlenden skills",
            "welche skills sollten dazu",
            "welche skills waeren hilfreich",
            "welche skills wären hilfreich",
            "priorisieren",
        ],
    )

    if _contains_any(
        normalized_user_text,
        [
            "welche skills hast",
            "welche skills sind installiert",
            "installierte skills",
            "installed skills",
            "runtime-skills",
            "runtime skills",
            "aktive skills",
            "list_skills",
        ],
    ) or "list_skills" in suggested_tools or has_generic_skill_inventory_question:
        _add("runtime_skills")

    if _has_explicit_draft_skill_signal(normalized_user_text):
        _add("draft_skills")

    if _contains_any(
        normalized_user_text,
        [
            "unterschied zwischen tools und skills",
            "unterschied zwischen skill und tool",
            "tools und skills",
            "tool und skill",
            "faehigkeiten",
            "fähigkeiten",
            "warum zeigt list_skills nicht",
        ],
    ) or has_generic_skill_inventory_question:
        _add("tools_vs_skills")

    if _contains_any(
        normalized_user_text,
        [
            "session skills",
            "session-skills",
            "codex skills",
            "codex-skill",
            "skill.md",
            "system skills",
            "system-skills",
        ],
    ):
        _add("session_skills")

    if _contains_any(
        normalized_user_text,
        [
            "welche arten von skills",
            "arten von skills",
            "skill-arten",
            "skill arten",
            "kategorien von skills",
            "was ist ein skill",
            "was sind skills",
        ],
    ) or has_generic_skill_inventory_question:
        _add("overview")

    if has_followup_brainstorm_signal and (
        has_generic_skill_inventory_question or "list_skills" in suggested_tools
    ):
        _add("fact_then_followup")

    return hints


def coerce_thinking_plan_schema(
    thinking_plan: Dict[str, Any],
    *,
    user_text: str = "",
    max_memory_keys_per_request: int,
    contains_explicit_tool_intent_fn: Callable[[str], bool],
    has_memory_recall_signal_fn: Callable[[str], bool],
) -> Dict[str, Any]:
    plan = thinking_plan if isinstance(thinking_plan, dict) else {}
    if not plan:
        return plan

    fixes: List[str] = []

    normalized_user_text = str(user_text or "").strip().lower()

    def _coerce_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return bool(value)
        low = str(value).strip().lower()
        if low in {"true", "1", "yes", "ja", "on"}:
            return True
        if low in {"false", "0", "no", "nein", "off", ""}:
            return False
        return default

    bool_keys = (
        "needs_memory",
        "is_fact_query",
        "needs_chat_history",
        "is_new_fact",
        "needs_sequential_thinking",
        "sequential_thinking_required",
        "social_memory_candidate",
        "grounding_relaxed_for_conversation",
    )
    for key in bool_keys:
        if key in plan:
            old = plan.get(key)
            new = _coerce_bool(old, default=False)
            if old != new:
                fixes.append(f"coerce_bool:{key}")
            plan[key] = new

    risk = str(plan.get("hallucination_risk") or "").strip().lower()
    if risk not in {"low", "medium", "high"}:
        plan["hallucination_risk"] = "medium"
        fixes.append("enum:hallucination_risk")

    act = str(plan.get("dialogue_act") or "").strip().lower()
    if act and act not in {"ack", "feedback", "question", "request", "analysis", "smalltalk"}:
        plan["dialogue_act"] = "request"
        fixes.append("enum:dialogue_act")
    elif act:
        if str(plan.get("dialogue_act")) != act:
            fixes.append("normalize:dialogue_act")
        plan["dialogue_act"] = act

    tone = str(plan.get("response_tone") or "").strip().lower()
    if tone and tone not in {"mirror_user", "warm", "neutral", "formal"}:
        plan["response_tone"] = "neutral"
        fixes.append("enum:response_tone")
    elif tone:
        if str(plan.get("response_tone")) != tone:
            fixes.append("normalize:response_tone")
        plan["response_tone"] = tone

    length = str(plan.get("response_length_hint") or "").strip().lower()
    if length and length not in {"short", "medium", "long"}:
        plan["response_length_hint"] = "medium"
        fixes.append("enum:response_length_hint")
    elif length:
        if str(plan.get("response_length_hint")) != length:
            fixes.append("normalize:response_length_hint")
        plan["response_length_hint"] = length

    conversation_mode = str(plan.get("conversation_mode") or "").strip().lower()
    if conversation_mode and conversation_mode not in {
        "conversational",
        "factual_light",
        "tool_grounded",
        "mixed",
    }:
        plan["conversation_mode"] = "factual_light"
        fixes.append("enum:conversation_mode")
    elif conversation_mode:
        if str(plan.get("conversation_mode")) != conversation_mode:
            fixes.append("normalize:conversation_mode")
        plan["conversation_mode"] = conversation_mode

    raw_keys = plan.get("memory_keys", [])
    normalized_keys: List[str] = []
    if isinstance(raw_keys, list):
        seen = set()
        for item in raw_keys:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized_keys.append(text)
            if len(normalized_keys) >= int(max(1, max_memory_keys_per_request)):
                break
    elif raw_keys:
        normalized_keys = [str(raw_keys).strip()]
        fixes.append("coerce_list:memory_keys")
    plan["memory_keys"] = normalized_keys

    raw_tools = plan.get("suggested_tools", [])
    if isinstance(raw_tools, list):
        plan["suggested_tools"] = raw_tools
    elif raw_tools:
        plan["suggested_tools"] = [raw_tools]
        fixes.append("coerce_list:suggested_tools")
    else:
        plan["suggested_tools"] = []

    raw_strategy = plan.get("resolution_strategy")
    strategy = str(raw_strategy or "").strip().lower()
    if strategy in {"", "null", "none", "false"}:
        plan["resolution_strategy"] = None
    elif strategy in _ALLOWED_RESOLUTION_STRATEGIES:
        plan["resolution_strategy"] = strategy
        if raw_strategy != strategy:
            fixes.append("normalize:resolution_strategy")
    else:
        plan["resolution_strategy"] = None
        fixes.append("enum:resolution_strategy")

    raw_hints = plan.get("strategy_hints", [])
    normalized_hints: List[str] = []
    if isinstance(raw_hints, list):
        seen_hints = set()
        hint_aliases = {
            "wishlist": "fact_then_followup",
            "wish_list": "fact_then_followup",
            "wunsch_skills": "fact_then_followup",
            "wunschskills": "fact_then_followup",
            "builtin_tools": "tools_vs_skills",
            "built_in_tools": "tools_vs_skills",
            "system_layers": "tools_vs_skills",
            "capabilities": "tools_vs_skills",
        }
        for item in raw_hints:
            hint = str(item or "").strip().lower()
            hint = hint_aliases.get(hint, hint)
            if not hint or hint in seen_hints:
                continue
            seen_hints.add(hint)
            normalized_hints.append(hint)
    elif raw_hints:
        normalized_hints = [str(raw_hints).strip().lower()]
        fixes.append("coerce_list:strategy_hints")
    plan["strategy_hints"] = normalized_hints

    suggested_tool_names = _tool_name_list(plan.get("suggested_tools", []))

    if not plan.get("resolution_strategy"):
        has_deictic_container = _contains_any(
            normalized_user_text,
            [
                "diesem container",
                "dieser container",
                "in diesem container",
                "this container",
                "current container",
            ],
        )
        has_capability_question = _contains_any(
            normalized_user_text,
            [
                "was kannst du",
                "was kann ich",
                "welche tools",
                "was ist hier installiert",
                "wofuer ist er da",
                "wofür ist er da",
                "alles tun",
            ],
        )
        has_excluded_runtime_intent = _contains_any(
            normalized_user_text,
            [
                "logs",
                "log ",
                "stat",
                "cpu",
                "ram",
                "memory",
                "stop",
                "start",
                "restart",
            ],
        )
        if bool(plan.get("is_fact_query")) and has_deictic_container and has_capability_question and not has_excluded_runtime_intent:
            plan["resolution_strategy"] = "active_container_capability"
            fixes.append("infer:resolution_strategy")

    if not plan.get("resolution_strategy"):
        if _has_container_request_signal(normalized_user_text) or any(
            name in {"request_container", "home_start"} for name in suggested_tool_names
        ):
            plan["resolution_strategy"] = "container_request"
            fixes.append("infer:resolution_strategy")

    if not plan.get("resolution_strategy"):
        if "blueprint_list" in suggested_tool_names or _has_container_blueprint_signal(normalized_user_text):
            plan["resolution_strategy"] = "container_blueprint_catalog"
            fixes.append("infer:resolution_strategy")

    if not plan.get("resolution_strategy"):
        has_state_tool_signal = any(name in {"container_inspect"} for name in suggested_tool_names)
        if bool(plan.get("is_fact_query")) and (_has_container_state_signal(normalized_user_text) or has_state_tool_signal):
            plan["resolution_strategy"] = "container_state_binding"
            fixes.append("infer:resolution_strategy")

    if not plan.get("resolution_strategy"):
        has_inventory_tool_signal = any(name in {"container_list"} for name in suggested_tool_names)
        if bool(plan.get("is_fact_query")) and (_has_container_inventory_signal(normalized_user_text) or has_inventory_tool_signal):
            plan["resolution_strategy"] = "container_inventory"
            fixes.append("infer:resolution_strategy")

    if not plan.get("resolution_strategy"):
        has_skill_markers = _contains_any(
            normalized_user_text,
            [
                " skill",
                "skills",
                "skill?",
                "skill.",
                "skill,",
                "skill:",
                "skill.md",
                "list_skills",
            ],
        ) or normalized_user_text.startswith("skill")
        has_skill_semantic_question = _contains_any(
            normalized_user_text,
            [
                "welche skills hast",
                "welche skills sind installiert",
                "welche arten von skills",
                "was ist der unterschied zwischen tools und skills",
                "was ist der unterschied zwischen skill und tool",
                "was fehlt dir an skills",
                "welche draft skills",
                "was sind draft skills",
                "welche session skills",
                "welche codex skills",
                "welche faehigkeiten",
                "welche fähigkeiten",
                "warum zeigt list_skills nicht",
            ],
        )
        has_skill_action_intent = _contains_any(
            normalized_user_text,
            [
                "create skill",
                "skill erstellen",
                "erstelle skill",
                "run skill",
                "skill ausführen",
                "skill ausfuehren",
                "führe skill",
                "fuehre skill",
                "installiere skill",
                "skill installieren",
                "validate skill",
                "validiere skill",
                "baue skill",
                "schreibe skill",
            ],
        ) or any(name in {"create_skill", "run_skill", "autonomous_skill_task", "validate_skill_code"} for name in suggested_tool_names)
        if has_skill_markers and has_skill_semantic_question and not has_skill_action_intent:
            plan["resolution_strategy"] = "skill_catalog_context"
            fixes.append("infer:resolution_strategy")

    if plan.get("resolution_strategy") == "skill_catalog_context":
        raw_skill_hints = list(plan.get("strategy_hints") or [])
        inferred_skill_hints = _infer_skill_strategy_hints(normalized_user_text, suggested_tool_names)
        canonical_skill_hints = [
            hint for hint in inferred_skill_hints
            if hint in _ALLOWED_SKILL_CATALOG_HINTS
        ]
        if raw_skill_hints:
            plan["_raw_strategy_hints"] = raw_skill_hints
        if raw_skill_hints != canonical_skill_hints:
            fixes.append("canonicalize:strategy_hints")
        plan["strategy_hints"] = canonical_skill_hints
        if any(hint in plan["strategy_hints"] for hint in {"runtime_skills", "draft_skills", "tools_vs_skills", "session_skills", "overview"}):
            fixes.append("infer:strategy_hints")

        if isinstance(plan.get("suggested_tools"), list):
            explicit_draft_signal = _has_explicit_draft_skill_signal(normalized_user_text)
            filtered_tools = []
            changed_tools = False
            has_list_skills = False
            for tool in plan["suggested_tools"]:
                name = str(tool.get("tool") or tool.get("name") or "").strip().lower() if isinstance(tool, dict) else str(tool or "").strip().lower()
                if name == "list_draft_skills" and not explicit_draft_signal:
                    changed_tools = True
                    continue
                if name == "list_skills":
                    has_list_skills = True
                filtered_tools.append(tool)
            if (
                not explicit_draft_signal
                and any(
                    (
                        str(tool.get("tool") or tool.get("name") or "").strip().lower()
                        if isinstance(tool, dict)
                        else str(tool or "").strip().lower()
                    ) == "list_draft_skills"
                    for tool in list(plan.get("suggested_tools") or [])
                )
                and not has_list_skills
            ):
                filtered_tools.append("list_skills")
                changed_tools = True
            if changed_tools:
                plan["suggested_tools"] = filtered_tools
                fixes.append("canonicalize:suggested_tools")

    route = plan.get("_domain_route") or {}
    route = route if isinstance(route, dict) else {}
    domain_tag = str(route.get("domain_tag") or "").strip().upper()
    domain_locked = bool(route.get("domain_locked"))
    explicit_tool_intent = contains_explicit_tool_intent_fn(user_text)
    recall_signal = has_memory_recall_signal_fn(user_text)
    if plan.get("needs_memory") and not plan.get("memory_keys"):
        if (domain_locked and domain_tag in {"CONTAINER", "SKILL", "CRONJOB"}) or explicit_tool_intent:
            if not recall_signal:
                plan["needs_memory"] = False
                plan["is_fact_query"] = False
                fixes.append("guard:drop_empty_memory_for_domain_or_tool_intent")

    pre_trace_fixes = list(plan.get("_schema_coercion") or [])
    plan = normalize_internal_loop_analysis_plan(
        plan,
        user_text=user_text,
        contains_explicit_tool_intent=explicit_tool_intent,
        has_memory_recall_signal=recall_signal,
    )
    post_trace_fixes = list(plan.get("_schema_coercion") or [])
    for item in post_trace_fixes:
        if item not in pre_trace_fixes and item not in fixes:
            fixes.append(item)

    if fixes:
        plan["_schema_coercion"] = fixes[-12:]
    return plan
