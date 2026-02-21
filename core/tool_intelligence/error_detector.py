"""
Tool Intelligence - Error Detection Module

Classifies tool errors and determines if they are retryable.
"""

from typing import Dict, Any, Optional
from utils.logger import log_info, log_warn, log_error, log_debug


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
    elif isinstance(result, dict) and result.get('error') is not None:
        if not result.get('success', True):
            is_error = True
            error_msg = str(result['error'])
    
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
    # PLACEHOLDER for Phase 3
    # For now, just return basic classification
    return {
        'retryable': True,
        'error_type': 'unknown',
        'category': 'general',
        'confidence': 0.5
    }
