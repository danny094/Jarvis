from typing import List, Dict


def build_prompt(messages):
    """
    Baut aus einer LobeChat-Nachrichtenliste
    ein einfaches Prompt-Format für Ollama.
    """
    parts = []

    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")

        if not content:
            continue

        if role == "system":
            prefix = "[SYSTEM]"
        elif role == "assistant":
            prefix = "[ASSISTANT]"
        else:
            prefix = "[USER]"

        parts.append(f"{prefix}: {content}")

    parts.append("[ASSISTANT]:")
    return "\n".join(parts)