import pytest
import sys
import os

# Add skill-server directory to path to import secret_scanner
skill_server_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../mcp-servers/skill-server"))
if skill_server_path not in sys.path:
    sys.path.append(skill_server_path)

from secret_scanner import SecretScanner

def test_hardcoded_secret_detection():
    scanner = SecretScanner()
    scanner.mode = "strict"
    
    code_with_leak = "API_KEY = 'AKIAIOSFODNN7EXAMPLE'"
    result = scanner.enforce(code_with_leak)
    assert not result["passed"]
    assert "secret_policy_violation" in result["error"]
    
def test_direct_env_access_detection():
    scanner = SecretScanner()
    scanner.mode = "strict"
    
    code_with_leak = "import os\\nkey = os.getenv('API_KEY')"
    result = scanner.enforce(code_with_leak)
    assert not result["passed"]
    assert "secret_policy_violation" in result["error"]
    
def test_valid_get_secret():
    scanner = SecretScanner()
    scanner.mode = "strict"
    
    valid_code = "key = get_secret('MY_APP_KEY')\\nprint('ok')"
    result = scanner.enforce(valid_code)
    assert result["passed"]
    assert not result["warnings"]

def test_warn_mode():
    scanner = SecretScanner()
    scanner.mode = "warn"
    
    code_with_leak = "API_KEY = 'AKIAIOSFODNN7EXAMPLE'"
    result = scanner.enforce(code_with_leak)
    # Warn mode passes but includes warnings
    assert result["passed"]
    assert len(result["warnings"]) > 0
    assert result["error"] is None
