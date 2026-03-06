"""
Tool Intelligence - Error Detection Module

Classifies tool errors and determines if they are retryable.
"""

import re
from typing import Dict, Any, Optional
from utils.logger import log_info, log_warn, log_error, log_debug
from core.tool_execution_policy import load_tool_execution_policy


def _has_meaningful_error(value: Any) -> bool:
    """Return True only for non-empty error payloads."""
    if value is None:
        return False
    if isinstance(value, str):
        lowered = value.strip().lower()
        return lowered not in ("", "none", "null")
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) > 0
    return True


def _stringify_error_value(value: Any, max_len: int = 240) -> str:
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (dict, list, tuple, set)):
        try:
            text = str(value)
        except Exception:
            text = "<complex error payload>"
    else:
        text = str(value)
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def _collect_semantic_errors(
    value: Any,
    *,
    keys: set[str],
    ignore_paths: set[str],
    max_depth: int,
    max_hits: int,
    depth: int = 0,
    path: Optional[list[str]] = None,
    hits: Optional[list[tuple[str, str]]] = None,
) -> list[tuple[str, str]]:
    if hits is None:
        hits = []
    if path is None:
        path = []
    if len(hits) >= max_hits or depth > max_depth:
        return hits

    if isinstance(value, dict):
        for k, v in value.items():
            key = str(k or "").strip()
            if not key:
                continue
            child_path = path + [key]
            path_str = ".".join(child_path).lower()
            if path_str in ignore_paths:
                continue
            if key.lower() in keys and _has_meaningful_error(v):
                hits.append((path_str, _stringify_error_value(v)))
                if len(hits) >= max_hits:
                    return hits
            if isinstance(v, (dict, list)):
                _collect_semantic_errors(
                    v,
                    keys=keys,
                    ignore_paths=ignore_paths,
                    max_depth=max_depth,
                    max_hits=max_hits,
                    depth=depth + 1,
                    path=child_path,
                    hits=hits,
                )
                if len(hits) >= max_hits:
                    return hits
        return hits

    if isinstance(value, list):
        for idx, item in enumerate(value):
            child_path = path + [f"[{idx}]"]
            path_str = ".".join(child_path).lower()
            if path_str in ignore_paths:
                continue
            if isinstance(item, (dict, list)):
                _collect_semantic_errors(
                    item,
                    keys=keys,
                    ignore_paths=ignore_paths,
                    max_depth=max_depth,
                    max_hits=max_hits,
                    depth=depth + 1,
                    path=child_path,
                    hits=hits,
                )
                if len(hits) >= max_hits:
                    return hits
        return hits

    return hits


def detect_tool_error(result: Any) -> tuple[bool, Optional[str]]:
    """
    Detect if a tool execution failed.
    
    Args:
        result: Tool execution result (ToolResult object, dict, or string)
        
    Returns:
        (is_error, error_message)
    """
    is_error = False
    error_msg = None
    
    # Check ToolResult object
    if hasattr(result, 'success'):
        if not result.success:
            is_error = True
            error_msg = getattr(result, 'error', None) or "Unknown error"
            if hasattr(result, 'content') and result.content:
                error_msg += f"\nDetails: {result.content}"
    
    # Check dict with error key
    # WICHTIG: run_skill gibt {"success": true, "result": ..., "error": null} zurück.
    # Nur als Fehler werten wenn: error ist nicht None UND success ist nicht True.
    elif isinstance(result, dict) and "error" in result:
        err_value = result.get("error")
        if _has_meaningful_error(err_value) and result.get("success") is not True:
            is_error = True
            error_msg = str(err_value)
    
    # Check semantic nested errors (policy-based, model-agnostic)
    if not is_error and isinstance(result, dict):
        policy = load_tool_execution_policy()
        sem_cfg = (policy or {}).get("semantic_error", {})
        if bool(sem_cfg.get("enabled", True)):
            keys = {
                str(k).strip().lower()
                for k in sem_cfg.get("keys", ["error", "errors", "exception", "traceback", "failure", "failure_reason"])
                if str(k).strip()
            }
            ignore_paths = {
                str(p).strip().lower()
                for p in sem_cfg.get("ignore_paths", [])
                if str(p).strip()
            }
            try:
                max_depth = max(1, int(sem_cfg.get("max_depth", 4)))
            except Exception:
                max_depth = 4
            try:
                max_hits = max(1, int(sem_cfg.get("max_hits", 3)))
            except Exception:
                max_hits = 3

            hits = _collect_semantic_errors(
                result,
                keys=keys or {"error"},
                ignore_paths=ignore_paths,
                max_depth=max_depth,
                max_hits=max_hits,
            )

            # Backward-compat: top-level success=true + error field should not flip to error
            # unless nested semantic errors exist (e.g. result.error in run_skill payload).
            top_success = result.get("success") is True
            if top_success:
                hits = [(path, msg) for path, msg in hits if path != "error"]

            if hits:
                first_path, first_msg = hits[0]
                is_error = True
                error_msg = f"semantic_error@{first_path}: {first_msg}"
    
    # Check String errors (common pattern)
    elif isinstance(result, str):
        result_lower = result.lower()
        if (result.startswith("Error:") or 
            result.startswith("error:") or
            "error:" in result_lower[:50] or
            any(kw in result_lower[:100] for kw in ["failed", "missing", "required", "invalid"])):
            is_error = True
            error_msg = result
    
    return is_error, error_msg


def classify_error(error_msg: str, tool_name: str) -> Dict[str, Any]:
    """
    Classify error type and determine if retryable.
    
    Returns:
        {
            'retryable': bool,
            'error_type': str,
            'category': str,
            'confidence': float
        }
    """
    message = (error_msg or "").strip()
    lowered = message.lower()

    if not lowered:
        return {
            'retryable': False,
            'error_type': 'empty_error',
            'category': 'unknown',
            'confidence': 0.2
        }

    def _contains_any(patterns: list[str]) -> bool:
        return any(pattern in lowered for pattern in patterns)

    if _contains_any([
        "permission denied",
        "access denied",
        "unauthorized",
        "forbidden",
        "not allowed",
        " 401",
        " 403",
    ]):
        return {
            'retryable': False,
            'error_type': 'permission_denied',
            'category': 'auth',
            'confidence': 0.95
        }

    if _contains_any([
        "rate limit",
        "too many requests",
        "quota exceeded",
        " 429",
    ]):
        return {
            'retryable': False,
            'error_type': 'rate_limited',
            'category': 'quota',
            'confidence': 0.9
        }

    if _contains_any([
        "not found",
        "does not exist",
        "unknown tool",
        "no such file",
        "module not found",
    ]):
        return {
            'retryable': False,
            'error_type': 'not_found',
            'category': 'resource',
            'confidence': 0.9
        }

    if _contains_any([
        "already exists",
        "conflict",
        "duplicate",
    ]):
        return {
            'retryable': False,
            'error_type': 'conflict',
            'category': 'state',
            'confidence': 0.85
        }

    if _contains_any([
        "timeout",
        "timed out",
        "temporarily unavailable",
        "connection reset",
        "connection refused",
        "try again",
        "service unavailable",
        "gateway timeout",
    ]):
        return {
            'retryable': True,
            'error_type': 'transient',
            'category': 'infrastructure',
            'confidence': 0.75
        }

    validation_patterns = [
        "required",
        "missing",
        "invalid",
        "must be",
        "should be",
        "wrong type",
        "parameter",
        "argument",
        "schema",
        "validation",
        "valueerror",
        "typeerror",
    ]
    if _contains_any(validation_patterns) or re.search(r"\bexpected\b", lowered):
        confidence = 0.85
        if tool_name == "create_skill" and _contains_any(["name", "description", "code"]):
            confidence = 0.95
        return {
            'retryable': True,
            'error_type': 'validation',
            'category': 'input',
            'confidence': confidence
        }

    # Safe default: unknown errors are not auto-retried.
    return {
        'retryable': False,
        'error_type': 'unknown',
        'category': 'general',
        'confidence': 0.4
    }
