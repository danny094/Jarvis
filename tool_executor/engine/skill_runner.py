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
ALLOWED_MODULES = {
    'json', 'math', 'datetime', 'time', 're', 
    'collections', 'itertools', 'functools',
    'typing', 'dataclasses', 'enum',
    'hashlib', 'base64', 'uuid',
    'logging', 'traceback',
    # Async
    'asyncio',
    # HTTP (controlled)
    'urllib.parse',
}

# Blocked modules
BLOCKED_MODULES = {
    'os', 'sys', 'subprocess', 'shutil', 'pathlib',
    'socket', 'http', 'urllib.request', 'requests',
    'pickle', 'marshal', 'shelve',
    'ctypes', 'multiprocessing',
    'importlib', 'builtins', '__builtins__'
}


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
        self.restricted_builtins = create_restricted_builtins()
        self.restricted_import = create_restricted_import()
    
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
        
        # Create restricted globals
        restricted_globals = {
            '__builtins__': self.restricted_builtins,
            '__name__': f'skill_{skill_name}',
            '__file__': str(entrypoint),
            '__import__': self.restricted_import,
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
