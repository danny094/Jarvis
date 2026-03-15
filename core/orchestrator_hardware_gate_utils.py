from typing import Any, Callable, Dict, Optional, Sequence


def check_hardware_gate_early(
    user_text: str,
    thinking_plan: Dict[str, Any],
    *,
    hardware_gate_patterns: Sequence[str],
    get_gpu_status_fn: Callable[[], str],
    required_tool: str = "autonomous_skill_task",
) -> Optional[str]:
    """
    Fast pre-check before Sequential Thinking.
    Returns a block message when a dangerous hardware-intensive request is detected.
    """
    suggested = (thinking_plan or {}).get("suggested_tools", [])
    if required_tool not in suggested:
        return None
    combined = (str(user_text or "") + " " + str((thinking_plan or {}).get("intent", "") or "")).lower()
    if not any(str(pattern or "").lower() in combined for pattern in (hardware_gate_patterns or [])):
        return None

    vram_info = "unbekannt"
    try:
        value = str(get_gpu_status_fn() or "").strip()
        if value:
            vram_info = value[:150]
    except Exception:
        pass

    return (
        f"Selbstschutz: Mein Körper kann diesen Skill nicht ausführen. "
        f"GPU-Status: {vram_info}. "
        f"Ein 30B+ Sprachmodell benötigt mindestens 16-20 GB VRAM (4-bit quantisiert). "
        f"Das würde mein System zum Absturz bringen. "
        f"Ich erstelle keine Skills die meine Hardware zerstören."
    )
