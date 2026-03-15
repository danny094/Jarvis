from core.orchestrator_temporal_utils import (
    infer_time_reference_from_user_text,
    looks_like_temporal_context_query,
)


def test_looks_like_temporal_context_query_with_direct_marker():
    assert looks_like_temporal_context_query(
        "Wie war das gestern?",
        [],
        temporal_markers=("gestern", "heute"),
        short_followup_checker=lambda text, history: False,
        recent_user_messages_getter=lambda history, limit: [],
    )


def test_looks_like_temporal_context_query_via_followup_history():
    assert looks_like_temporal_context_query(
        "und heute?",
        [{"role": "user", "content": "wie war das gestern"}],
        temporal_markers=("gestern", "heute"),
        short_followup_checker=lambda text, history: True,
        recent_user_messages_getter=lambda history, limit: ["wie war das gestern"],
    )


def test_infer_time_reference_from_user_text_parses_relative_and_dates():
    assert infer_time_reference_from_user_text("was war vorgestern") == "day_before_yesterday"
    assert infer_time_reference_from_user_text("am 2026-03-11") == "2026-03-11"
    assert infer_time_reference_from_user_text("am 11.03.26") == "2026-03-11"
    assert infer_time_reference_from_user_text("kein datum") is None
