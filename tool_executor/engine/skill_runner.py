"""
Secure Skill Runner - Sandboxed Execution Engine
Layer 4 - Tool Executor

Security Features:
- Restricted builtins (no eval, exec, open, etc.)
- Timeout protection
- Resource monitoring
- Audit logging
"""

import importlib.util
import asyncio
import os
import sys
import signal
import json
import re
import urllib.request
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass
from contextlib import contextmanager
import threading

# Observability
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from observability.events import EventLogger


@dataclass
class ExecutionResult:
    success: bool
    result: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0
    sandbox_violations: list = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
            "sandbox_violations": self.sandbox_violations or []
        }


# === SANDBOX CONFIGURATION ===

# Dangerous builtins to remove
BLOCKED_BUILTINS = {
    'eval', 'exec', 'compile', 'open', '__import__',
    'globals', 'locals', 'vars', 'dir',
    'getattr', 'setattr', 'delattr',
    'input', 'breakpoint'
}

# Allowed modules for skills
# Keep this aligned with tool_executor.api.PACKAGE_ALLOWLIST and
# skill-server package detection/mapping.
ALLOWED_MODULES = {
    'json', 'math', 'datetime', 'time', 're',
    'collections', 'itertools', 'functools',
    'typing', 'dataclasses', 'enum',
    'hashlib', 'base64', 'uuid',
    'logging', 'traceback',
    # Async
    'asyncio',
    # HTTP (für API-Skills: Wetter, Daten abrufen etc.)
    'urllib.parse', 'urllib.request', 'urllib.error',
    'http', 'http.client',
    'requests', 'httpx', 'aiohttp',
    # Data/processing (from package allowlist)
    'numpy', 'pandas', 'scipy', 'matplotlib',
    # Parsing/content
    'bs4', 'lxml', 'xmltodict',
    # Utility libs where import name differs from package name
    'PIL',        # pillow
    'dateutil',   # python-dateutil
    'dotenv',     # python-dotenv
    'Levenshtein',  # python-levenshtein
    # Misc allowlisted modules
    'pytz', 'arrow', 'qrcode', 'toml', 'nltk', 'fuzzywuzzy',
    # System-Monitoring (read-only, kein Schreibzugriff)
    'psutil', 'platform', 'GPUtil',
}

# Blocked modules (System-Zugriff, Datei-Zugriff, Code-Ausführung)
BLOCKED_MODULES = {
    'os', 'sys', 'subprocess', 'shutil', 'pathlib',
    'socket',
    'pickle', 'marshal', 'shelve',
    'ctypes', 'multiprocessing',
    'importlib', 'builtins', '__builtins__'
}

EXECUTOR_PYTHON_VENV = os.getenv("EXECUTOR_PYTHON_VENV", "/tmp/trion-tool-executor-venv")


def _venv_site_packages_paths(venv_dir: str) -> list[str]:
    """Return candidate site-packages paths for the configured venv."""
    major = sys.version_info.major
    minor = sys.version_info.minor
    version_dir = f"python{major}.{minor}"
    return [
        os.path.join(venv_dir, "lib", version_dir, "site-packages"),
        os.path.join(venv_dir, "lib64", version_dir, "site-packages"),
    ]


def _normalize_secret_name(name: str) -> str:
    """Normalize secret names to stable UPPER_SNAKE_CASE."""
    if not isinstance(name, str):
        return ""
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", name.strip().upper())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized[:128]


def _extract_secret_names(payload: Any) -> list[str]:
    """Extract secret names from list payloads with flexible shapes."""
    names: list[str] = []

    def _append(candidate: Any):
        if isinstance(candidate, str):
            cleaned = candidate.strip()
            if cleaned:
                names.append(cleaned)
            return
        if isinstance(candidate, dict):
            value = candidate.get("name")
            if isinstance(value, str) and value.strip():
                names.append(value.strip())

    if isinstance(payload, dict):
        for key in ("secrets", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                for entry in value:
                    _append(entry)
        nested_result = payload.get("result")
        if isinstance(nested_result, dict):
            nested_secrets = nested_result.get("secrets")
            if isinstance(nested_secrets, list):
                for entry in nested_secrets:
                    _append(entry)
    elif isinstance(payload, list):
        for entry in payload:
            _append(entry)

    # Preserve order, remove duplicates.
    deduped: list[str] = []
    seen: set[str] = set()
    for name in names:
        norm = _normalize_secret_name(name)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        deduped.append(name)
    return deduped


def _find_secret_alias(requested_name: str, available_names: list[str]) -> str:
    """
    Deterministic alias resolution:
    - exact match
    - *_API_KEY <-> *_KEY swap
    - BASE -> unique BASE_API_KEY/BASE_KEY
    """
    requested_norm = _normalize_secret_name(requested_name)
    if not requested_norm:
        return ""

    norm_to_original: Dict[str, str] = {}
    for name in available_names:
        normalized = _normalize_secret_name(name)
        if normalized and normalized not in norm_to_original:
            norm_to_original[normalized] = name

    if requested_norm in norm_to_original:
        return norm_to_original[requested_norm]

    if requested_norm.endswith("_API_KEY"):
        alt = f"{requested_norm[:-8]}_KEY"
        return norm_to_original.get(alt, "")

    if requested_norm.endswith("_KEY"):
        alt = f"{requested_norm[:-4]}_API_KEY"
        return norm_to_original.get(alt, "")

    candidates = [f"{requested_norm}_API_KEY", f"{requested_norm}_KEY"]
    matches = [norm_to_original[candidate] for candidate in candidates if candidate in norm_to_original]
    if len(matches) == 1:
        return matches[0]
    return ""


def _resolve_secret_value(secrets_resolve_url: str, token: str, name: str, timeout: int = 5) -> str:
    normalized_name = _normalize_secret_name(name)
    if not normalized_name:
        return ""
    try:
        req = urllib.request.Request(f"{secrets_resolve_url.rstrip('/')}/{normalized_name}")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read())
        value = payload.get("value")
        return value if isinstance(value, str) else ""
    except Exception:
        return ""


def _fetch_secret_names(secrets_list_url: str, token: str, timeout: int = 5) -> list[str]:
    try:
        req = urllib.request.Request(secrets_list_url.rstrip("/"))
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read())
        return _extract_secret_names(payload)
    except Exception:
        return []


def create_restricted_builtins() -> Dict[str, Any]:
    """Create a restricted builtins dict for sandboxed execution."""
    import builtins
    safe_builtins = {}
    
    for name in dir(builtins):
        if name not in BLOCKED_BUILTINS and not name.startswith('_'):
            safe_builtins[name] = getattr(builtins, name)
    
    # Add safe print that logs
    original_print = builtins.print
    def safe_print(*args, **kwargs):
        EventLogger.emit("skill_print", {"output": " ".join(str(a) for a in args)})
        # Don't actually print to stdout in production
        pass
    
    safe_builtins['print'] = safe_print
    
    return safe_builtins


def create_restricted_import() -> Callable:
    """Create a restricted __import__ function."""
    original_import = __builtins__['__import__'] if isinstance(__builtins__, dict) else __import__
    
    def restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
        # Check if module is blocked
        base_module = name.split('.')[0]
        
        if base_module in BLOCKED_MODULES or name in BLOCKED_MODULES:
            raise ImportError(f"Module '{name}' is not allowed in skills (security restriction)")
        
        if base_module not in ALLOWED_MODULES and name not in ALLOWED_MODULES:
            raise ImportError(f"Module '{name}' is not in the allowed list for skills")
        
        return original_import(name, globals, locals, fromlist, level)
    
    return restricted_import


class TimeoutError(Exception):
    """Raised when skill execution times out."""
    pass


@contextmanager
def timeout_context(seconds: int):
    """Context manager for execution timeout."""
    def timeout_handler(signum, frame):
        raise TimeoutError(f"Skill execution timed out after {seconds} seconds")
    
    # Set the signal handler
    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)
    
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


class SkillRunner:
    """Secure skill execution engine."""
    
    def __init__(self, skills_dir: str = "/skills", timeout_seconds: int = 30):
        self.skills_dir = Path(skills_dir)
        self.timeout_seconds = timeout_seconds
        self._inject_executor_venv_site_packages()
        self.restricted_builtins = create_restricted_builtins()
        self.restricted_import = create_restricted_import()

    def _inject_executor_venv_site_packages(self):
        """
        Make packages from executor venv importable for sandboxed skills.
        No-op when venv does not exist.
        """
        for candidate in _venv_site_packages_paths(EXECUTOR_PYTHON_VENV):
            if os.path.isdir(candidate) and candidate not in sys.path:
                sys.path.insert(0, candidate)
    
    def _find_entrypoint(self, skill_name: str) -> Optional[Path]:
        """Find the skill entrypoint file."""
        skill_path = self.skills_dir / skill_name
        
        # Check common entrypoints
        for filename in ["main.py", "run.py", "__init__.py"]:
            entrypoint = skill_path / filename
            if entrypoint.exists():
                return entrypoint
        
        return None
    
    def _load_module_sandboxed(self, skill_name: str, entrypoint: Path) -> Any:
        """Load a skill module with sandbox restrictions."""
        
        # Read the source code
        with open(entrypoint, 'r') as f:
            source_code = f.read()
        
        # Inject get_secret() — resolves encrypted API keys at runtime
        _secrets_resolve_url = os.getenv(
            "SECRETS_API_URL",
            "http://jarvis-admin-api:8200/api/secrets/resolve",
        )
        _secrets_list_url = _secrets_resolve_url.rstrip("/")
        if _secrets_list_url.endswith("/resolve"):
            _secrets_list_url = _secrets_list_url[:-len("/resolve")]
        _secret_alias_mode = os.getenv("SKILL_SECRET_ALIAS_MODE", "safe").strip().lower()
        
        _internal_token = ""
        try:
            from config import get_secret_resolve_token
            _internal_token = get_secret_resolve_token()
        except ImportError:
            _internal_token = os.getenv("INTERNAL_SECRET_RESOLVE_TOKEN", "")

        def _get_secret(name: str) -> str:
            try:
                requested = _normalize_secret_name(name)
                if not requested:
                    return ""

                # 1) Try exact name first.
                value = _resolve_secret_value(_secrets_resolve_url, _internal_token, requested, timeout=5)
                if value:
                    return value

                # 2) Optional deterministic alias fallback.
                if _secret_alias_mode == "off":
                    return ""

                available_names = _fetch_secret_names(_secrets_list_url, _internal_token, timeout=5)
                alias = _find_secret_alias(requested, available_names)
                if not alias:
                    return ""

                resolved_alias = _normalize_secret_name(alias)
                if not resolved_alias or resolved_alias == requested:
                    return ""

                value = _resolve_secret_value(_secrets_resolve_url, _internal_token, resolved_alias, timeout=5)
                if value:
                    EventLogger.emit(
                        "skill_secret_alias_match",
                        {"requested": requested, "resolved": resolved_alias},
                    )
                return value
            except Exception:
                return ""

        # Create restricted globals
        restricted_globals = {
            '__builtins__': self.restricted_builtins,
            '__name__': f'skill_{skill_name}',
            '__file__': str(entrypoint),
            '__import__': self.restricted_import,
            'get_secret': _get_secret,
        }
        
        # Add restricted import to builtins
        self.restricted_builtins['__import__'] = self.restricted_import
        
        # Compile and execute in sandbox
        compiled = compile(source_code, str(entrypoint), 'exec')
        exec(compiled, restricted_globals)
        
        return restricted_globals
    
    async def run(
        self, 
        skill_name: str, 
        action: str = "run", 
        args: Optional[Dict[str, Any]] = None
    ) -> ExecutionResult:
        """
        Execute a skill action in a sandboxed environment.
        
        Args:
            skill_name: Name of the skill to run
            action: Function name to call (default: "run")
            args: Arguments to pass to the function
            
        Returns:
            ExecutionResult with success status and result/error
        """
        import time
        start_time = time.time()
        args = args or {}
        violations = []
        
        EventLogger.emit("skill_run_start", {
            "skill": skill_name,
            "action": action,
            "has_args": bool(args)
        })
        
        # 1. Find entrypoint
        entrypoint = self._find_entrypoint(skill_name)
        if not entrypoint:
            return ExecutionResult(
                success=False,
                error=f"Skill '{skill_name}' not found or has no entrypoint"
            )
        
        try:
            # 2. Load module in sandbox with timeout
            with timeout_context(self.timeout_seconds):
                module_globals = self._load_module_sandboxed(skill_name, entrypoint)
                
                # 3. Find and call the action
                if action not in module_globals:
                    return ExecutionResult(
                        success=False,
                        error=f"Action '{action}' not found in skill '{skill_name}'"
                    )
                
                func = module_globals[action]
                
                if not callable(func):
                    return ExecutionResult(
                        success=False,
                        error=f"'{action}' is not callable"
                    )
                
                # 4. Execute the function
                if asyncio.iscoroutinefunction(func):
                    result = await func(**args)
                else:
                    result = func(**args)
                
                execution_time = (time.time() - start_time) * 1000
                
                EventLogger.emit("skill_run_complete", {
                    "skill": skill_name,
                    "action": action,
                    "execution_time_ms": execution_time
                })
                
                return ExecutionResult(
                    success=True,
                    result=result,
                    execution_time_ms=execution_time,
                    sandbox_violations=violations
                )
                
        except TimeoutError as e:
            EventLogger.emit("skill_run_timeout", {
                "skill": skill_name,
                "timeout_seconds": self.timeout_seconds
            }, status="error")
            return ExecutionResult(
                success=False,
                error=str(e)
            )
            
        except ImportError as e:
            # Sandbox violation - blocked import
            violations.append(f"Blocked import: {e}")
            EventLogger.emit("skill_sandbox_violation", {
                "skill": skill_name,
                "violation": str(e)
            }, status="error")
            return ExecutionResult(
                success=False,
                error=f"Security violation: {e}",
                sandbox_violations=violations
            )
            
        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            EventLogger.emit("skill_run_error", {
                "skill": skill_name,
                "error": str(e),
                "error_type": type(e).__name__
            }, status="error")
            return ExecutionResult(
                success=False,
                error=f"{type(e).__name__}: {str(e)}",
                execution_time_ms=execution_time
            )


# Singleton instance
_runner_instance: Optional[SkillRunner] = None

def get_skill_runner() -> SkillRunner:
    """Get the singleton SkillRunner instance."""
    global _runner_instance
    if _runner_instance is None:
        _runner_instance = SkillRunner(
            skills_dir=os.getenv("SKILLS_DIR", "/skills"),
            timeout_seconds=int(os.getenv("SKILL_TIMEOUT", "30"))
        )
    return _runner_instance
