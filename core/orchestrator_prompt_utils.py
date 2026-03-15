import hashlib
import json
import re
import uuid
from typing import Any, Dict, List, Optional, Sequence


def normalize_trace_id(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        raw = uuid.uuid4().hex[:12]
    safe = re.sub(r"[^a-zA-Z0-9:_-]", "", raw)[:64]
    return safe or uuid.uuid4().hex[:12]


def safe_str(value: Any, *, max_len: int = 3000) -> str:
    text = str(value or "").strip()
    if len(text) > max_len:
        return text[:max_len]
    return text


def is_rollout_enabled(rollout_pct: int, seed: str) -> bool:
    try:
        pct = int(rollout_pct)
    except Exception:
        pct = 100
    pct = max(0, min(100, pct))
    if pct >= 100:
        return True
    if pct <= 0:
        return False
    token = str(seed or "global")
    bucket = int(hashlib.sha1(token.encode("utf-8")).hexdigest()[:8], 16) % 100
    return bucket < pct


def message_role_value(msg: Any) -> str:
    role = getattr(msg, "role", None)
    if hasattr(role, "value"):
        return str(role.value).strip().lower()
    if role is not None:
        return str(role).strip().lower()
    if isinstance(msg, dict):
        return str(msg.get("role", "")).strip().lower()
    return ""


def message_content_value(msg: Any) -> str:
    content = getattr(msg, "content", None)
    if content is not None:
        return str(content)
    if isinstance(msg, dict):
        return str(msg.get("content", ""))
    return ""


def last_assistant_message(chat_history: Optional[list]) -> str:
    if not isinstance(chat_history, list):
        return ""
    for item in reversed(chat_history):
        if message_role_value(item) == "assistant":
            return message_content_value(item).strip()
    return ""


def recent_user_messages(chat_history: Optional[list], limit: int = 3) -> List[str]:
    if not isinstance(chat_history, list):
        return []
    out: List[str] = []
    for item in reversed(chat_history):
        if message_role_value(item) != "user":
            continue
        content = message_content_value(item).strip()
        if content:
            out.append(content)
        if len(out) >= max(1, limit):
            break
    return out


def looks_like_short_fact_followup(
    user_text: str,
    chat_history: Optional[list],
    *,
    prefixes: Sequence[str],
    markers: Sequence[str],
) -> bool:
    text = str(user_text or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if len(lowered) > 220:
        return False
    if lowered.startswith(tuple(prefixes)):
        return True

    has_followup_marker = any(tok in lowered for tok in markers)
    if not has_followup_marker:
        return False

    prev_assistant = last_assistant_message(chat_history)
    if not prev_assistant:
        return False
    if "verifizierte fakten" in prev_assistant.lower():
        return True
    return len(lowered) <= 100 and "?" in lowered


def looks_like_short_confirmation_followup(
    user_text: str,
    chat_history: Optional[list],
    *,
    prefixes: Sequence[str],
    markers: Sequence[str],
    assistant_action_markers: Sequence[str],
) -> bool:
    text = str(user_text or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if len(lowered) > 120:
        return False

    starts_with_prefix = lowered.startswith(tuple(prefixes))
    has_marker = any(tok in lowered for tok in markers)
    if not (starts_with_prefix or has_marker):
        return False

    prev_assistant = last_assistant_message(chat_history).lower()
    if not prev_assistant:
        return False

    # Confirmation follow-ups only when assistant previously asked for an action/decision.
    asked_for_decision = (
        "soll ich" in prev_assistant
        or "möchtest du" in prev_assistant
        or "moechtest du" in prev_assistant
        or "?" in prev_assistant
    )
    if not asked_for_decision:
        return False

    return any(tok in prev_assistant for tok in assistant_action_markers)


def looks_like_short_confirmation_followup_state_only(
    user_text: str,
    *,
    action_markers: Sequence[str],
) -> bool:
    text = str(user_text or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if len(lowered) > 120:
        return False
    if "?" in lowered:
        return False
    return any(tok in lowered for tok in action_markers)


def sanitize_tool_args_for_state(value: Any, *, non_serialized_max_len: int = 200) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    safe: Dict[str, Any] = {}
    for k, v in value.items():
        key = str(k or "").strip()
        if not key:
            continue
        try:
            json.dumps(v, ensure_ascii=False, default=str)
            safe[key] = v
        except Exception:
            safe[key] = safe_str(v, max_len=non_serialized_max_len)
    return safe


def expected_home_blueprint_id(default: str = "trion-home") -> str:
    try:
        from utils.trion_home_identity import load_home_identity

        identity = load_home_identity(create_if_missing=False)
        value = str(identity.get("container_id", "")).strip()
        if value:
            return value
    except Exception:
        pass
    return default
