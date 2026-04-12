from core.orchestrator_plan_schema_utils import coerce_thinking_plan_schema


def test_coerce_thinking_plan_schema_normalizes_bool_enums_and_lists():
    raw = {
        "needs_memory": "true",
        "is_fact_query": "false",
        "needs_chat_history": "1",
        "hallucination_risk": "unknown",
        "dialogue_act": "REQUEST",
        "response_tone": "LOUD",
        "response_length_hint": "verbose",
        "memory_keys": "",
        "suggested_tools": "exec_in_container",
    }
    out = coerce_thinking_plan_schema(
        raw,
        user_text="Nutze bitte Tools.",
        max_memory_keys_per_request=5,
        contains_explicit_tool_intent_fn=lambda text: True,
        has_memory_recall_signal_fn=lambda text: False,
    )
    assert out["needs_memory"] is False
    assert out["is_fact_query"] is False
    assert out["needs_chat_history"] is True
    assert out["hallucination_risk"] == "medium"
    assert out["dialogue_act"] == "request"
    assert out["response_tone"] == "neutral"
    assert out["response_length_hint"] == "medium"
    assert out["memory_keys"] == []
    assert out["suggested_tools"] == ["exec_in_container"]
    assert isinstance(out.get("_schema_coercion"), list)


def test_coerce_thinking_plan_schema_preserves_memory_for_recall_signal():
    raw = {
        "needs_memory": True,
        "is_fact_query": True,
        "memory_keys": [],
        "_domain_route": {"domain_tag": "CONTAINER", "domain_locked": True},
    }
    out = coerce_thinking_plan_schema(
        raw,
        user_text="Was hast du dir über meine Präferenz gemerkt?",
        max_memory_keys_per_request=5,
        contains_explicit_tool_intent_fn=lambda text: True,
        has_memory_recall_signal_fn=lambda text: True,
    )
    assert out["needs_memory"] is True
    assert out["is_fact_query"] is True


def test_coerce_thinking_plan_schema_infers_active_container_capability_strategy():
    raw = {
        "needs_memory": True,
        "is_fact_query": True,
        "needs_chat_history": True,
        "memory_keys": ["active_container_id"],
        "suggested_tools": ["container_stats", "exec_in_container"],
    }
    out = coerce_thinking_plan_schema(
        raw,
        user_text="Was kannst du in diesem container alles tun?",
        max_memory_keys_per_request=5,
        contains_explicit_tool_intent_fn=lambda text: False,
        has_memory_recall_signal_fn=lambda text: False,
    )
    assert out["resolution_strategy"] == "active_container_capability"
    assert "infer:resolution_strategy" in out.get("_schema_coercion", [])


def test_coerce_thinking_plan_schema_infers_container_inventory_strategy():
    raw = {
        "needs_memory": False,
        "is_fact_query": True,
        "needs_chat_history": False,
        "memory_keys": [],
        "suggested_tools": [],
    }
    out = coerce_thinking_plan_schema(
        raw,
        user_text="Welche Container laufen gerade und welche sind gestoppt?",
        max_memory_keys_per_request=5,
        contains_explicit_tool_intent_fn=lambda text: False,
        has_memory_recall_signal_fn=lambda text: False,
    )
    assert out["resolution_strategy"] == "container_inventory"
    assert "infer:resolution_strategy" in out.get("_schema_coercion", [])


def test_coerce_thinking_plan_schema_infers_container_blueprint_catalog_strategy():
    raw = {
        "needs_memory": False,
        "is_fact_query": True,
        "needs_chat_history": False,
        "memory_keys": [],
        "suggested_tools": [],
    }
    out = coerce_thinking_plan_schema(
        raw,
        user_text="Welche Blueprints gibt es und welche Container kann ich starten?",
        max_memory_keys_per_request=5,
        contains_explicit_tool_intent_fn=lambda text: False,
        has_memory_recall_signal_fn=lambda text: False,
    )
    assert out["resolution_strategy"] == "container_blueprint_catalog"
    assert "infer:resolution_strategy" in out.get("_schema_coercion", [])


def test_coerce_thinking_plan_schema_infers_container_state_binding_strategy():
    raw = {
        "needs_memory": False,
        "is_fact_query": True,
        "needs_chat_history": False,
        "memory_keys": [],
        "suggested_tools": [],
    }
    out = coerce_thinking_plan_schema(
        raw,
        user_text="Welcher Container ist gerade aktiv und auf welchen Container ist dieser Turn gebunden?",
        max_memory_keys_per_request=5,
        contains_explicit_tool_intent_fn=lambda text: False,
        has_memory_recall_signal_fn=lambda text: False,
    )
    assert out["resolution_strategy"] == "container_state_binding"
    assert "infer:resolution_strategy" in out.get("_schema_coercion", [])


def test_coerce_thinking_plan_schema_infers_container_request_strategy():
    raw = {
        "needs_memory": False,
        "is_fact_query": False,
        "needs_chat_history": False,
        "memory_keys": [],
        "suggested_tools": [],
    }
    out = coerce_thinking_plan_schema(
        raw,
        user_text="Starte einen Python-Container fuer mich.",
        max_memory_keys_per_request=5,
        contains_explicit_tool_intent_fn=lambda text: True,
        has_memory_recall_signal_fn=lambda text: False,
    )
    assert out["resolution_strategy"] == "container_request"
    assert "infer:resolution_strategy" in out.get("_schema_coercion", [])


def test_coerce_thinking_plan_schema_infers_skill_catalog_context_and_hints():
    raw = {
        "needs_memory": False,
        "is_fact_query": True,
        "needs_chat_history": False,
        "memory_keys": [],
        "suggested_tools": ["list_skills"],
    }
    out = coerce_thinking_plan_schema(
        raw,
        user_text="Was ist der Unterschied zwischen Tools und Skills?",
        max_memory_keys_per_request=5,
        contains_explicit_tool_intent_fn=lambda text: False,
        has_memory_recall_signal_fn=lambda text: False,
    )
    assert out["resolution_strategy"] == "skill_catalog_context"
    assert "tools_vs_skills" in out["strategy_hints"]
    assert "answering_rules" in out["strategy_hints"]
    assert "skill_taxonomy" in out["strategy_hints"]
    assert "infer:resolution_strategy" in out.get("_schema_coercion", [])


def test_coerce_thinking_plan_schema_does_not_relabel_skill_execution_as_catalog_context():
    raw = {
        "needs_memory": False,
        "is_fact_query": False,
        "memory_keys": [],
        "suggested_tools": ["run_skill"],
    }
    out = coerce_thinking_plan_schema(
        raw,
        user_text="Führe den Skill current_weather aus.",
        max_memory_keys_per_request=5,
        contains_explicit_tool_intent_fn=lambda text: True,
        has_memory_recall_signal_fn=lambda text: False,
    )
    assert out["resolution_strategy"] is None


def test_coerce_thinking_plan_schema_sharpens_live_skill_inventory_hints():
    raw = {
        "needs_memory": False,
        "is_fact_query": True,
        "needs_chat_history": False,
        "memory_keys": [],
        "resolution_strategy": "skill_catalog_context",
        "strategy_hints": ["runtime_skills", "draft_skills", "overview"],
        "suggested_tools": ["list_skills"],
    }
    out = coerce_thinking_plan_schema(
        raw,
        user_text=(
            "Dir stehen SKILLS zu verfügung. Kannst du mal schauen, "
            "was du darüber in erfahrung bringen kannst? "
            "Was für skills hättest du gerne?"
        ),
        max_memory_keys_per_request=5,
        contains_explicit_tool_intent_fn=lambda text: False,
        has_memory_recall_signal_fn=lambda text: False,
    )
    assert out["resolution_strategy"] == "skill_catalog_context"
    assert "runtime_skills" in out["strategy_hints"]
    assert "overview" in out["strategy_hints"]
    assert "tools_vs_skills" in out["strategy_hints"]
    assert "answering_rules" in out["strategy_hints"]
    assert "fact_then_followup" in out["strategy_hints"]


def test_coerce_thinking_plan_schema_canonicalizes_skill_catalog_hints_and_tools():
    raw = {
        "needs_memory": False,
        "is_fact_query": True,
        "needs_chat_history": False,
        "memory_keys": [],
        "resolution_strategy": "skill_catalog_context",
        "strategy_hints": [
            "runtime_skills",
            "draft_skills",
            "builtin_tools",
            "system_layers",
            "wishlist",
            "garbage_hint",
        ],
        "suggested_tools": ["list_skills", "list_draft_skills"],
    }
    out = coerce_thinking_plan_schema(
        raw,
        user_text="Welche Skills hast du aktuell und welche Skills wuerdest du dir als Naechstes wuenschen?",
        max_memory_keys_per_request=5,
        contains_explicit_tool_intent_fn=lambda text: False,
        has_memory_recall_signal_fn=lambda text: False,
    )
    assert out["resolution_strategy"] == "skill_catalog_context"
    assert out["_raw_strategy_hints"] == [
        "runtime_skills",
        "draft_skills",
        "tools_vs_skills",
        "fact_then_followup",
        "garbage_hint",
    ]
    assert "runtime_skills" in out["strategy_hints"]
    assert "tools_vs_skills" in out["strategy_hints"]
    assert "fact_then_followup" in out["strategy_hints"]
    assert "draft_skills" not in out["strategy_hints"]
    assert "builtin_tools" not in out["strategy_hints"]
    assert "system_layers" not in out["strategy_hints"]
    assert "garbage_hint" not in out["strategy_hints"]
    assert out["suggested_tools"] == ["list_skills"]


def test_coerce_thinking_plan_schema_maps_wishlist_hint_to_fact_then_followup():
    raw = {
        "needs_memory": False,
        "is_fact_query": True,
        "needs_chat_history": False,
        "memory_keys": [],
        "resolution_strategy": "skill_catalog_context",
        "strategy_hints": ["runtime_skills", "wishlist"],
        "suggested_tools": ["list_skills"],
    }
    out = coerce_thinking_plan_schema(
        raw,
        user_text="Welche Skills hast du aktuell und welche Skills wuerdest du dir als Naechstes wuenschen?",
        max_memory_keys_per_request=5,
        contains_explicit_tool_intent_fn=lambda text: False,
        has_memory_recall_signal_fn=lambda text: False,
    )
    assert out["resolution_strategy"] == "skill_catalog_context"
    assert "fact_then_followup" in out["strategy_hints"]


def test_coerce_thinking_plan_schema_normalizes_internal_loop_analysis_prompt():
    raw = {
        "needs_memory": True,
        "memory_keys": ["multistep_loop_status", "error_logs"],
        "needs_chat_history": True,
        "is_fact_query": False,
        "resolution_strategy": "active_container_capability",
        "strategy_hints": ["runtime_skills", "checkpoint_status"],
        "suggested_tools": [
            "memory_graph_search",
            "container_inspect",
            "exec_in_container",
            "snapshot_list",
        ],
        "needs_sequential_thinking": True,
    }
    out = coerce_thinking_plan_schema(
        raw,
        user_text="Pruefe kurz den neuen Multistep Loop und zeige mir sichere Zwischenstaende",
        max_memory_keys_per_request=5,
        contains_explicit_tool_intent_fn=lambda text: False,
        has_memory_recall_signal_fn=lambda text: False,
    )
    assert out["resolution_strategy"] is None
    assert out["suggested_tools"] == []
    assert out["needs_memory"] is False
    assert out["memory_keys"] == []
    assert out["_loop_trace_mode"] == "internal_loop_analysis"
    trace = out.get("_loop_trace_normalization") or {}
    corrections = trace.get("corrections") or []
    assert any(item.get("field") == "resolution_strategy" for item in corrections)
    assert any(item.get("field") == "suggested_tools" for item in corrections)
    assert any(item.get("field") == "needs_memory" for item in corrections)


def test_coerce_thinking_plan_schema_marks_internal_loop_analysis_even_without_corrections():
    raw = {
        "intent": "Loop pruefen",
        "needs_memory": False,
        "memory_keys": [],
        "needs_chat_history": True,
        "is_fact_query": False,
        "resolution_strategy": None,
        "strategy_hints": ["analysis"],
        "suggested_tools": [],
        "needs_sequential_thinking": False,
    }
    out = coerce_thinking_plan_schema(
        raw,
        user_text="Pruefe kurz den neuen Multistep Loop und zeige mir sichere Zwischenstaende",
        max_memory_keys_per_request=5,
        contains_explicit_tool_intent_fn=lambda text: False,
        has_memory_recall_signal_fn=lambda text: False,
    )
    assert out["_loop_trace_mode"] == "internal_loop_analysis"
    trace = out.get("_loop_trace_normalization") or {}
    assert trace.get("mode") == "internal_loop_analysis"
    assert trace.get("reason") == "prompt_matches_internal_loop_analysis"
    assert trace.get("corrections") == []
    assert "normalize:internal_loop_analysis" in list(out.get("_schema_coercion") or [])
