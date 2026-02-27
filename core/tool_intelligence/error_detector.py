"""
Tool Intelligence - Error Detection Module

Classifies tool errors and determines if they are retryable.
"""

import re
from typing import Dict, Any, Optional
from utils.logger import log_info, log_warn, log_error, log_debug


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
