# mcp-servers/skill-server/secret_scanner.py
"""
C8 Secret Policy Scanner
Detects hardcoded secrets or direct os.getenv/os.environ usage.
Forces the usage of get_secret("NAME").
"""

import re
import ast
import os

def _get_enforcement_mode() -> str:
    """Robust fallback if config.py isn't fully synchronized."""
    try:
        from config import get_skill_secret_enforcement
        return get_skill_secret_enforcement()
    except (ImportError, ModuleNotFoundError):
        val = os.getenv("SKILL_SECRET_ENFORCEMENT", "warn").lower()
        return val if val in ("warn", "strict") else "warn"

class SecretScanner:
    def __init__(self):
        self.mode = _get_enforcement_mode()
        
        # Heuristics for hardcoded secrets
        # Matches typical variable names assigned to a string of >= 10 chars
        self.hardcode_pattern = re.compile(
            r'(?i)(api_?key|token|secret|password|auth)\s*[:=]\s*[\'"][a-zA-Z0-9_\-\.]{10,}[\'"]'
        )
        
        # Patterns for direct OS env access
        self.env_pattern = re.compile(r'os\.getenv\(|os\.environ\b')

    def scan_skill_code(self, code: str) -> list[str]:
        """
        Scans skill code for secret policy violations.
        Returns a list of warning/error messages. Empty list means passed.
        """
        violations = []
        
        if not code:
            return violations
            
        # 1. Regex check for hardcoded secrets
        if self.hardcode_pattern.search(code):
            violations.append("Possible hardcoded secret detected. Use get_secret('NAME') instead.")
            
        # 2. Regex check for os.environ / os.getenv
        if self.env_pattern.search(code):
            violations.append("Direct environment access (os.getenv/os.environ) is forbidden for secrets. Use get_secret('NAME').")
            
        return violations
        
    def enforce(self, code: str) -> dict:
        """
        Runs the scanner and applies the enforcement policy (warn vs strict).
        Returns a dict with 'passed' (bool), 'warnings' (list), and 'error' (str).
        """
        violations = self.scan_skill_code(code)
        
        if not violations:
            return {"passed": True, "warnings": [], "error": None}
            
        if self.mode == "strict":
            # Fail closed on security uncertainty without leaking matched values
            return {
                "passed": False, 
                "warnings": violations, 
                "error": "secret_policy_violation"
            }
            
        # warn mode
        return {"passed": True, "warnings": violations, "error": None}
