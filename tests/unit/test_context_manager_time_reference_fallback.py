from unittest.mock import patch


def _make_cm():
    from core.context_manager import ContextManager
    return ContextManager()


def test_context_manager_infers_today_time_reference_for_temporal_followup():
    cm = _make_cm()
    thinking_plan = {
        "needs_chat_history": True,
        "needs_memory": False,
        "is_fact_query": False,
        "memory_keys": [],
    }
    with patch("core.context_manager.get_context_retrieval_budget_s", return_value=30.0), \
         patch("core.context_manager.get_memory_lookup_timeout_s", return_value=2.0), \
         patch("config.get_daily_context_followup_enable", return_value=True), \
         patch.object(cm, "_load_daily_protocol", return_value="TODAY-PROTOCOL") as mock_protocol, \
         patch.object(cm, "_load_trion_laws", return_value=""), \
         patch.object(cm, "_load_active_containers", return_value=""), \
         patch.object(cm, "_search_system_tools", return_value=""), \
         patch.object(cm, "_load_skill_knowledge_hint", return_value=""):
        result = cm.get_context(
            query="Was haben wir heute besprochen?",
            thinking_plan=thinking_plan,
            conversation_id="conv-1",
            small_model_mode=False,
        )
    assert "TODAY-PROTOCOL" in result.memory_data
    assert mock_protocol.call_args.kwargs.get("time_reference") == "today"


def test_context_manager_infers_yesterday_time_reference_for_temporal_followup():
    cm = _make_cm()
    thinking_plan = {
        "needs_chat_history": True,
        "needs_memory": False,
        "is_fact_query": False,
        "memory_keys": [],
    }
    with patch("core.context_manager.get_context_retrieval_budget_s", return_value=30.0), \
         patch("core.context_manager.get_memory_lookup_timeout_s", return_value=2.0), \
         patch("config.get_daily_context_followup_enable", return_value=True), \
         patch.object(cm, "_load_daily_protocol", return_value="YESTERDAY-PROTOCOL") as mock_protocol, \
         patch.object(cm, "_load_trion_laws", return_value=""), \
         patch.object(cm, "_load_active_containers", return_value=""), \
         patch.object(cm, "_search_system_tools", return_value=""), \
         patch.object(cm, "_load_skill_knowledge_hint", return_value=""):
        result = cm.get_context(
            query="Und was war gestern?",
            thinking_plan=thinking_plan,
            conversation_id="conv-1",
            small_model_mode=False,
        )
    assert "YESTERDAY-PROTOCOL" in result.memory_data
    assert mock_protocol.call_args.kwargs.get("time_reference") == "yesterday"
