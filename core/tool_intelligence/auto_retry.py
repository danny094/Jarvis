"""
Tool Intelligence - Auto-Retry Module

Attempts to fix tool errors and retry execution.
Based on error pattern analysis showing 85% of errors are create_skill parameter issues.
"""

from typing import Dict, Any, Optional, Tuple
from utils.logger import log_info, log_warn, log_error, log_debug


class AutoRetry:
    """
    Intelligent retry logic with parameter correction.
    
    Strategies:
    1. Parameter aliasing (skill_name -> name)
    2. Missing parameter generation (placeholder code)
    3. Loop prevention (max 2 retries)
    """
    
    # Parameter aliases per tool (from analysis)
    PARAM_ALIASES = {
        'create_skill': {
            'skill_name': 'name',
            'skillname': 'name',
            'source_code': 'code',
            'script': 'code',
            'skill_code': 'code',
            'content': 'description',
            'desc': 'description',
            'skill_description': 'description'
        },
        'memory_save': {
            'content': 'value',
            'topic': 'key',
            'data': 'value',
            'memory_key': 'key',
            'memory_value': 'value'
        },
        'workspace_save': {
            'content': 'entry_content',
            'text': 'entry_content',
            'data': 'entry_content'
        }
    }
    
    # Non-retryable error patterns
    NEVER_RETRY = [
        'permission denied',
        'unauthorized',
        'quota exceeded',
        'rate limit',
        'not found',
        'does not exist',
        'forbidden'
    ]
    
    def __init__(self):
        """Initialize retry tracker."""
        self.retry_counts = {}  # Track attempts: {retry_key: count}
        self.max_retries = 2
    
    def attempt_retry(
        self,
        tool_name: str,
        error_msg: str,
        original_args: Dict,
        tool_hub,
        retry_key: str = None
    ) -> Dict[str, Any]:
        """
        Attempt to fix and retry a failed tool call.
        
        Args:
            tool_name: Name of the failed tool
            error_msg: Error message from tool
            original_args: Original arguments that failed
            tool_hub: ToolHub instance to call tools
            retry_key: Unique key for tracking retries
            
        Returns:
            {
                'success': bool,
                'result': Any,
                'fix_applied': str,
                'attempts': int,
                'reason': str
            }
        """
        # Generate unique key for this retry attempt
        if not retry_key:
            retry_key = f"{tool_name}_{hash(str(original_args))}"
        
        # Check retry limit
        attempts = self.retry_counts.get(retry_key, 0)
        if attempts >= self.max_retries:
            log_warn(f"[AutoRetry] Max retries ({self.max_retries}) exceeded for {tool_name}")
            return {
                'success': False,
                'result': None,
                'fix_applied': '',
                'attempts': attempts,
                'reason': 'max_retries_exceeded'
            }
        
        # Check if error is retryable
        if not self._is_retryable(error_msg):
            log_debug(f"[AutoRetry] Error not retryable: {error_msg[:50]}")
            return {
                'success': False,
                'result': None,
                'fix_applied': '',
                'attempts': 0,
                'reason': 'non_retryable_error'
            }
        
        # Attempt to fix arguments
        fixed_args, fix_description = self._fix_arguments(
            tool_name, 
            error_msg, 
            original_args
        )
        
        if not fixed_args or fixed_args == original_args:
            log_debug(f"[AutoRetry] No fix available for {tool_name}")
            return {
                'success': False,
                'result': None,
                'fix_applied': '',
                'attempts': 0,
                'reason': 'no_fix_available'
            }
        
        # Increment retry counter
        self.retry_counts[retry_key] = attempts + 1
        
        # Execute retry
        log_info(f"[AutoRetry] Attempt {attempts + 1}/{self.max_retries} for {tool_name}")
        log_info(f"[AutoRetry] Fix: {fix_description}")
        log_info(f"[AutoRetry] Fixed args: {fixed_args}")
        
        try:
            # Call tool with fixed arguments
            result = tool_hub.call_tool(tool_name, fixed_args)
            
            # Check if retry succeeded
            retry_success = self._check_success(result)
            
            if retry_success:
                log_info(f"[AutoRetry] ✅ Success on attempt {attempts + 1}!")
                # Clear retry counter on success
                self.retry_counts.pop(retry_key, None)
            else:
                log_warn(f"[AutoRetry] ❌ Retry failed on attempt {attempts + 1}")
            
            return {
                'success': retry_success,
                'result': result,
                'fix_applied': fix_description,
                'attempts': attempts + 1,
                'reason': 'retry_success' if retry_success else 'retry_failed'
            }
            
        except Exception as e:
            log_error(f"[AutoRetry] Retry exception: {e}")
            return {
                'success': False,
                'result': None,
                'fix_applied': fix_description,
                'attempts': attempts + 1,
                'reason': f'exception: {str(e)}'
            }
    
    def _is_retryable(self, error_msg: str) -> bool:
        """
        Determine if error is retryable.
        
        Args:
            error_msg: Error message to check
            
        Returns:
            True if error can be retried
        """
        error_lower = error_msg.lower()
        
        # Never retry these errors
        for pattern in self.NEVER_RETRY:
            if pattern in error_lower:
                return False
        
        # Retryable error patterns
        retryable_patterns = [
            'required',
            'missing',
            'expected',
            'invalid format',
            'wrong type',
            'must be',
            'should be'
        ]
        
        return any(pattern in error_lower for pattern in retryable_patterns)
    
    def _check_success(self, result: Any) -> bool:
        """
        Check if tool execution was successful.
        
        Args:
            result: Tool execution result
            
        Returns:
            True if successful
        """
        # Check ToolResult object
        if hasattr(result, 'success'):
            return result.success
        
        # Check dict with error key
        if isinstance(result, dict) and 'error' in result:
            return False
        
        # Check string errors
        if isinstance(result, str):
            result_lower = result.lower()
            if result.startswith("Error:") or "error:" in result_lower[:50]:
                return False
        
        # Default to success
        return True
    
    def _fix_arguments(
        self, 
        tool_name: str, 
        error_msg: str, 
        args: Dict
    ) -> Tuple[Optional[Dict], str]:
        """
        Attempt to fix tool arguments.
        
        Args:
            tool_name: Name of the tool
            error_msg: Error message
            args: Original arguments
            
        Returns:
            (fixed_args, fix_description) or (None, reason)
        """
        fixes_applied = []
        fixed_args = args.copy()
        
        # Strategy 1: Apply parameter aliases
        if tool_name in self.PARAM_ALIASES:
            fixed_args, alias_desc = self._apply_aliases(tool_name, fixed_args)
            if alias_desc != 'no_aliases_applied':
                fixes_applied.append(alias_desc)
        
        # Strategy 2: Tool-specific fixes
        if tool_name == 'create_skill':
            fixed_args, skill_desc = self._fix_create_skill(fixed_args, error_msg)
            if skill_desc != 'no_fix_needed':
                fixes_applied.append(skill_desc)
        
        # Return result
        if fixes_applied:
            description = " | ".join(fixes_applied)
            return fixed_args, description
        
        return None, "no_fix_available"
    
    def _apply_aliases(self, tool_name: str, args: Dict) -> Tuple[Dict, str]:
        """
        Apply parameter name aliases.
        
        Args:
            tool_name: Tool name
            args: Original arguments
            
        Returns:
            (fixed_args, description)
        """
        aliases = self.PARAM_ALIASES.get(tool_name, {})
        fixed_args = args.copy()
        renamed = []
        
        for wrong_name, correct_name in aliases.items():
            if wrong_name in args and correct_name not in args:
                # Rename parameter
                fixed_args[correct_name] = fixed_args.pop(wrong_name)
                renamed.append(f"{wrong_name}→{correct_name}")
                log_debug(f"[AutoRetry] Renamed: {wrong_name} → {correct_name}")
        
        if renamed:
            return fixed_args, f"Renamed: {', '.join(renamed)}"
        
        return args, "no_aliases_applied"
    
    def _fix_create_skill(self, args: Dict, error_msg: str) -> Tuple[Dict, str]:
        """
        Special handling for create_skill errors.
        
        MVP Strategy:
        - If 'name' missing: Try to generate from description
        - If 'code' missing: Generate placeholder
        
        Args:
            args: Original arguments
            error_msg: Error message
            
        Returns:
            (fixed_args, description)
        """
        fixed_args = args.copy()
        fixes = []
        
        # Fix 1: Generate name if missing
        if 'name' not in fixed_args:
            # Try to extract from description
            if 'description' in fixed_args:
                import re
                desc = fixed_args['description']
                
                # Try patterns to extract skill name
                # Pattern 1: "mit dem namen X" or "namens X"
                match = re.search(r"(?:mit dem namen|namens|name)\s+(\w+)", desc, re.IGNORECASE)
                if match:
                    name = match.group(1).lower()
                else:
                    # Pattern 2: Last capitalized word
                    words = desc.split()
                    capitalized = [w for w in words if w and w[0].isupper()]
                    if capitalized:
                        name = capitalized[-1].lower()
                    else:
                        # Fallback: first meaningful word (skip "erstelle", "create", etc.)
                        skip_words = {'erstelle', 'create', 'mache', 'einen', 'skill', 'mit'}
                        meaningful = [w.lower() for w in words if w.lower() not in skip_words]
                        name = meaningful[0] if meaningful else 'auto_skill'
                
                fixed_args['name'] = name
                fixes.append(f"Generated name: '{name}'")
                log_debug(f"[AutoRetry] Generated name from description: {name}")
        
        # Fix 2: Generate placeholder code if missing
        if 'code' not in fixed_args:
            skill_name = fixed_args.get('name', 'auto_skill')
            # Sanitize function name (remove invalid chars)
            func_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in skill_name)
            
            placeholder_code = f"""def {func_name}():
    \"\"\"
    Auto-generated placeholder for {skill_name}.
    Replace this with actual skill logic.
    \"\"\"
    return "Skill {skill_name} executed successfully!"
"""
            fixed_args['code'] = placeholder_code
            fixes.append("Generated placeholder code")
            log_debug(f"[AutoRetry] Generated placeholder code for {skill_name}")
        
        # Fix 3: Replace or add proper description
        if 'name' in fixed_args:
            # Check if description is just the user query (not a real skill description)
            current_desc = fixed_args.get('description', '')
            if not current_desc or 'erstelle' in current_desc.lower() or 'create' in current_desc.lower():
                # Replace with proper description
                fixed_args['description'] = f"Auto-generated skill: {fixed_args['name']}"
                fixes.append("Replaced query with proper description")
            # else: Keep existing description if it looks valid
        
        if fixes:
            return fixed_args, " | ".join(fixes)
        
        return args, "no_fix_needed"
    
    def reset_retry_count(self, retry_key: str = None):
        """
        Reset retry counter for a specific key or all.
        
        Args:
            retry_key: Specific key to reset, or None for all
        """
        if retry_key:
            self.retry_counts.pop(retry_key, None)
        else:
            self.retry_counts.clear()
