from .config import MTM_KEYWORDS, LTM_KEYWORDS

def auto_assign_layer(role: str, content: str) -> str:
    """Automatische Layer-Erkennung basierend auf Inhalt und Rolle."""

    text = content.lower()

    if role == "system":
        return "ltm"

    if len(text) < 80:
        return "stm"

    if any(k in text for k in MTM_KEYWORDS):
        return "mtm"

    if any(k in text for k in LTM_KEYWORDS):
        return "ltm"

    return "mtm"
