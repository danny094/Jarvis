# modules/meta_decision/decision_client.py
"""
Meta-Decision Client.

Ruft den Decision-Layer direkt auf.
"""

from utils.logger import log_error, log_info


async def ask_meta_decision(user_text: str) -> dict:
    """
    Async Wrapper für den Meta-Decision-Layer.
    
    Returns:
        dict mit:
        - use_memory: bool
        - rewrite: str (optional)
        - update_memory: dict (optional)
    """
    from .decision import run_decision_layer
    
    payload = {
        "user": user_text,
        "memory": ""  # TODO: Memory-Kontext hinzufügen
    }
    
    try:
        result = await run_decision_layer(payload)
        log_info(f"[MetaDecision] → {result}")
        return result
        
    except Exception as e:
        log_error(f"[MetaDecision Client] Fehler: {e}")
        return {
            "use_memory": False,
            "rewrite": "",
            "update_memory": None,
        }
