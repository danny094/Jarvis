"""
Tool Intelligence - Manager

Coordinates error detection, search, and retry.
"""

from typing import Dict, Any, Optional
from .error_detector import detect_tool_error, classify_error
from .auto_search import AutoSearch
# from .auto_retry import AutoRetry  # Phase 3
from utils.logger import log_debug


class ToolIntelligenceManager:
    """
    Manages tool error handling, search, and retry logic.
    """
    
    def __init__(self, archive_manager):
        self.auto_search = AutoSearch(archive_manager)
        self.auto_retry = None  # Lazy initialization (needs tool_hub)
    
    def handle_tool_result(
        self, 
        tool_name: str, 
        result: Any,
        tool_args: Dict = None,
        tool_hub = None  # NEW: Required for retry
    ) -> Dict[str, Any]:
        """
        Handle tool execution result.
        
        Returns:
            {
                'is_error': bool,
                'error_msg': str,
                'solutions': str,
                'retry_result': dict  # Phase 3
            }
        """
        # Step 1: Detect error
        is_error, error_msg = detect_tool_error(result)
        
        if not is_error:
            return {
                'is_error': False,
                'error_msg': None,
                'solutions': '',
                'retry_result': None
            }
        
        # Step 2: Search for solutions
        solutions = self.auto_search.search_past_solutions(tool_name, error_msg)
        error_classification = classify_error(error_msg or "", tool_name)
        
        # Step 3: Attempt auto-retry
        retry_result = None
        if error_classification.get('retryable') and tool_hub and tool_args is not None:
            # Lazy initialize auto_retry
            if self.auto_retry is None:
                from .auto_retry import AutoRetry
                self.auto_retry = AutoRetry()
            
            # Attempt retry
            retry_result = self.auto_retry.attempt_retry(
                tool_name=tool_name,
                error_msg=error_msg,
                original_args=tool_args,
                tool_hub=tool_hub
            )
        elif not error_classification.get('retryable'):
            log_debug(
                f"[ToolIntelligence] Skip auto-retry for {tool_name}: "
                f"{error_classification.get('error_type', 'unknown')} "
                f"(confidence={error_classification.get('confidence', 0.0)})"
            )
        
        return {
            'is_error': True,
            'error_msg': error_msg,
            'solutions': solutions,
            'error_classification': error_classification,
            'retry_result': retry_result
        }
