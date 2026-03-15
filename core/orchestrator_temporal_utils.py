import re
from datetime import datetime
from typing import Any, Callable, Optional, Sequence


def looks_like_temporal_context_query(
    user_text: str,
    chat_history: Optional[list] = None,
    *,
    temporal_markers: Sequence[str],
    short_followup_checker: Callable[[str, Optional[list]], bool],
    recent_user_messages_getter: Callable[[Optional[list], int], list],
) -> bool:
    text = str(user_text or "").strip().lower()
    if not text:
        return False
    if any(marker in text for marker in temporal_markers):
        return True
    if not short_followup_checker(text, chat_history):
        return False
    recent_users = recent_user_messages_getter(chat_history, 3)
    for msg in recent_users:
        recent_text = str(msg or "").strip().lower()
        if any(marker in recent_text for marker in temporal_markers):
            return True
    return False


def infer_time_reference_from_user_text(user_text: str) -> Optional[str]:
    text = str(user_text or "").strip().lower()
    if not text:
        return None
    if "vorgestern" in text:
        return "day_before_yesterday"
    if "gestern" in text:
        return "yesterday"
    if "heute" in text:
        return "today"

    m_iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m_iso:
        y, mo, d = m_iso.groups()
        try:
            dt = datetime(int(y), int(mo), int(d))
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    m_eu = re.search(r"\b(\d{1,2})[./](\d{1,2})[./](\d{2,4})\b", text)
    if m_eu:
        d, mo, y = m_eu.groups()
        year = int(y)
        if year < 100:
            year += 2000
        try:
            dt = datetime(year, int(mo), int(d))
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    return None
