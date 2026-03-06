"""
Tests für B1: Memory Fallback Keys (context_manager.py)

Wenn ThinkingLayer needs_memory=True liefert aber memory_keys=[],
soll ContextManager automatisch Fallback-Keys verwenden.
"""
from unittest.mock import MagicMock, patch


FALLBACK_KEYS = ["user_facts", "personal_info", "preferences"]


def _make_cm():
    """Erzeugt eine ContextManager-Instanz."""
    from core.context_manager import ContextManager
    return ContextManager()


def _common_patches():
    """Patch-Stack für small_model_mode-Pfad."""
    return [
        patch("core.context_manager.get_context_retrieval_budget_s", return_value=30.0),
        patch("core.context_manager.get_memory_lookup_timeout_s", return_value=5.0),
    ]


# ---------------------------------------------------------------------------
# B1-Test 1: Fallback greift wenn needs_memory=True und keys=[]
# ---------------------------------------------------------------------------
def test_fallback_keys_used_when_needs_memory_true_and_keys_empty():
    cm = _make_cm()
    thinking_plan = {
        "needs_memory": True,
        "memory_keys": [],
        "is_fact_query": False,
    }
    called_with_keys = {}

    def fake_parallel(keys, **kwargs):
        called_with_keys["keys"] = list(keys)
        return {}

    patches = _common_patches()
    for p in patches:
        p.start()
    try:
        with patch.object(cm, "_load_trion_laws", return_value=""), \
             patch.object(cm, "_load_active_containers", return_value=""), \
             patch.object(cm, "_search_memory_keys_parallel", side_effect=fake_parallel):
            cm.get_context(
                query="Was mag ich?",
                thinking_plan=thinking_plan,
                conversation_id="conv-1",
                small_model_mode=True,
            )
    finally:
        for p in patches:
            p.stop()

    assert called_with_keys.get("keys") == FALLBACK_KEYS, (
        f"Erwartete Fallback-Keys {FALLBACK_KEYS}, bekam: {called_with_keys.get('keys')}"
    )


# ---------------------------------------------------------------------------
# B1-Test 2: Fallback NICHT angewendet wenn needs_memory=False
# ---------------------------------------------------------------------------
def test_fallback_not_applied_when_needs_memory_false():
    cm = _make_cm()
    thinking_plan = {
        "needs_memory": False,
        "memory_keys": [],
        "is_fact_query": False,
    }
    called_with_keys = {"called": False}

    def fake_parallel(keys, **kwargs):
        called_with_keys["called"] = True
        return {}

    patches = _common_patches()
    for p in patches:
        p.start()
    try:
        with patch.object(cm, "_load_trion_laws", return_value=""), \
             patch.object(cm, "_load_active_containers", return_value=""), \
             patch.object(cm, "_search_memory_keys_parallel", side_effect=fake_parallel):
            cm.get_context(
                query="Wie spät ist es?",
                thinking_plan=thinking_plan,
                conversation_id="conv-1",
                small_model_mode=True,
            )
    finally:
        for p in patches:
            p.stop()

    assert not called_with_keys["called"], (
        "memory_search darf nicht aufgerufen werden wenn needs_memory=False"
    )


# ---------------------------------------------------------------------------
# B1-Test 3: Fallback NICHT angewendet wenn keys bereits vorhanden sind
# ---------------------------------------------------------------------------
def test_fallback_not_applied_when_keys_already_present():
    cm = _make_cm()
    thinking_plan = {
        "needs_memory": True,
        "memory_keys": ["custom_key_1", "custom_key_2"],
        "is_fact_query": False,
    }
    called_with_keys = {}

    def fake_parallel(keys, **kwargs):
        called_with_keys["keys"] = list(keys)
        return {}

    patches = _common_patches()
    for p in patches:
        p.start()
    try:
        with patch.object(cm, "_load_trion_laws", return_value=""), \
             patch.object(cm, "_load_active_containers", return_value=""), \
             patch.object(cm, "_search_memory_keys_parallel", side_effect=fake_parallel):
            cm.get_context(
                query="Erinnere dich",
                thinking_plan=thinking_plan,
                conversation_id="conv-1",
                small_model_mode=True,
            )
    finally:
        for p in patches:
            p.stop()

    assert called_with_keys.get("keys") == ["custom_key_1", "custom_key_2"], (
        f"Vorhandene Keys dürfen nicht durch Fallback ersetzt werden: {called_with_keys.get('keys')}"
    )


# ---------------------------------------------------------------------------
# B1-Test 4: Budget-Erschöpfung blockiert auch Fallback-Keys
# ---------------------------------------------------------------------------
def test_fallback_respects_budget_check():
    cm = _make_cm()
    thinking_plan = {
        "needs_memory": True,
        "memory_keys": [],
        "is_fact_query": False,
    }
    called_with_keys = {"called": False}

    def fake_parallel(keys, **kwargs):
        called_with_keys["called"] = True
        return {}

    patches = [
        # Budget sofort erschöpft: deadline in der Vergangenheit
        patch("core.context_manager.get_context_retrieval_budget_s", return_value=0.0),
        patch("core.context_manager.get_memory_lookup_timeout_s", return_value=5.0),
    ]
    for p in patches:
        p.start()
    try:
        with patch.object(cm, "_load_trion_laws", return_value=""), \
             patch.object(cm, "_load_active_containers", return_value=""), \
             patch.object(cm, "_search_memory_keys_parallel", side_effect=fake_parallel):
            cm.get_context(
                query="Erinnere dich",
                thinking_plan=thinking_plan,
                conversation_id="conv-1",
                small_model_mode=True,
            )
    finally:
        for p in patches:
            p.stop()

    assert not called_with_keys["called"], (
        "memory_search darf bei erschöpftem Budget nicht aufgerufen werden, auch nicht mit Fallback-Keys"
    )
