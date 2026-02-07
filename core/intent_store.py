"""
IntentStore - Einfacher In-Memory Store für SkillCreationIntents

Fallback ohne SQL-Abhängigkeit für robuste Funktion.
"""

from typing import Dict, List, Optional
from .intent_models import SkillCreationIntent, IntentState
from utils.logger import log_info, log_error, log_warn

# Thread-safe In-Memory Storage
_INTENT_STORE: Dict[str, SkillCreationIntent] = {}


class IntentStore:
    """Singleton In-Memory Intent Store."""
    
    def __init__(self):
        pass  # Nutzt globalen _INTENT_STORE
    
    def add(self, intent: SkillCreationIntent) -> None:
        """Speichert einen Intent."""
        global _INTENT_STORE
        _INTENT_STORE[intent.id] = intent
        log_info(f"[IntentStore] Intent {intent.id[:8]} gespeichert (memory)")
    
    def get(self, intent_id: str) -> Optional[SkillCreationIntent]:
        """Holt einen Intent by ID."""
        return _INTENT_STORE.get(intent_id)
    
    def get_pending_for_conversation(self, conv_id: str) -> List[SkillCreationIntent]:
        """Holt alle pending Intents für eine Conversation."""
        result = []
        for intent in _INTENT_STORE.values():
            if (intent.conversation_id == conv_id and 
                intent.state == IntentState.PENDING_CONFIRMATION):
                result.append(intent)
        return result
    
    def update_state(self, intent_id: str, new_state: IntentState) -> None:
        """Aktualisiert den Status eines Intents."""
        intent = _INTENT_STORE.get(intent_id)
        if intent:
            intent.state = new_state
            log_info(f"[IntentStore] Intent {intent_id[:8]} -> {new_state.value}")
    
    def remove(self, intent_id: str) -> None:
        """Löscht einen Intent."""
        if intent_id in _INTENT_STORE:
            del _INTENT_STORE[intent_id]
            log_info(f"[IntentStore] Intent {intent_id[:8]} gelöscht")


def get_intent_store() -> IntentStore:
    """Factory-Funktion für IntentStore Singleton."""
    return IntentStore()
