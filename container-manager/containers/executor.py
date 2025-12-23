# containers/executor.py
"""
Code Execution in Containers.

Führt Code sicher in Docker-Containern aus.
"""

import io
import os
import re
import sys
import tarfile
import time
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass

# ============================================================
# PATH SETUP (für absolute Imports)
# ============================================================

# Füge Parent-Verzeichnis zum Pfad hinzu falls nötig
_parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)


# ============================================================
# IMPORTS MIT FALLBACK
# ============================================================

# Config
try:
    from config import MAX_OUTPUT_LENGTH, log_info, log_error
except ImportError:
    MAX_OUTPUT_LENGTH = 10000
    LOG_PREFIX = "[ContainerManager]"
    def log_info(msg: str) -> None:
        print(f"{LOG_PREFIX} [INFO] {msg}")
    def log_error(msg: str) -> None:
        print(f"{LOG_PREFIX} [ERROR] {msg}")

# Languages
try:
    from languages.config import get_language_config
except ImportError:
    # Fallback: Inline LANGUAGE_CONFIG
    _LANGUAGE_CONFIG = {
        "python": {"file": "code.py", "cmd": ["python", "/workspace/code.py"]},
        "bash": {"file": "code.sh", "cmd": ["bash", "/workspace/code.sh"]},
        "sh": {"file": "code.sh", "cmd": ["sh", "/workspace/code.sh"]},
        "javascript": {"file": "code.js", "cmd": ["node", "/workspace/code.js"]},
        "js": {"file": "code.js", "cmd": ["node", "/workspace/code.js"]},
        "node": {"file": "code.js", "cmd": ["node", "/workspace/code.js"]},
        "ruby": {"file": "code.rb", "cmd": ["ruby", "/workspace/code.rb"]},
        "php": {"file": "code.php", "cmd": ["php", "/workspace/code.php"]},
    }
    def get_language_config(language: str) -> dict:
        lang = (language or "python").lower().strip()
        return _LANGUAGE_CONFIG.get(lang, _LANGUAGE_CONFIG["python"])

# Security: Validator
try:
    from security.validator import validate_code, sanitize_output
except ImportError:
    # Fallback: Simple validation
    MAX_CODE_LENGTH = 100000
    BLOCKED_PATTERNS = [
        r"rm\s+-rf\s+/",
        r":\(\)\s*\{\s*:\|:&",
        r"dd\s+if=/dev/zero",
    ]
    
    def validate_code(code: str, language: str) -> Tuple[bool, Optional[str], List[str]]:
        if not code or not code.strip():
            return False, "Leerer Code", []
        if len(code) > MAX_CODE_LENGTH:
            return False, f"Code zu groß ({len(code)} bytes)", []
        code_lower = code.lower()
        for pattern in BLOCKED_PATTERNS:
            if re.search(pattern, code_lower, re.IGNORECASE):
                return False, "Blockiertes Pattern erkannt", []
        return True, None, []
    
    def sanitize_output(output: str, max_length: int = 10000) -> str:
        if not output:
            return ""
        if len(output) > max_length:
            output = output[:max_length] + f"\n... (gekürzt, {len(output)} total)"
        return output

# Security: Limits
try:
    from security.limits import ResourceLimits
except ImportError:
    # Fallback: Inline ResourceLimits
    @dataclass
    class ResourceLimits:
        memory: str = "512m"
        cpus: float = 1.0
        pids: int = 100
        disk: str = "100m"
        timeout: int = 60
        
        @classmethod
        def from_config(cls, config: Dict[str, Any]) -> "ResourceLimits":
            resources = config.get("resources", {})
            security = config.get("security", {})
            return cls(
                memory=resources.get("memory", "512m"),
                cpus=float(resources.get("cpus", 1.0)),
                pids=int(resources.get("pids_limit", 100)),
                timeout=min(int(security.get("max_runtime_seconds", 60)), 300),
            )
        
        def get_timeout_command(self, cmd: list) -> list:
            return ["timeout", str(self.timeout)] + cmd


# ============================================================
# EXECUTION RESULT
# ============================================================

@dataclass
class ExecutionResult:
    """Ergebnis einer Code-Ausführung."""
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    language: str = "python"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }
    
    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.error


# ============================================================
# CODE EXECUTOR
# ============================================================

class CodeExecutor:
    """
    Führt Code sicher in Docker-Containern aus.
    
    Features:
    - Timeout-Schutz
    - Output-Sanitization
    - Multi-Language Support
    - Code-Validation
    """
    
    def __init__(
        self,
        container,
        limits: Optional[ResourceLimits] = None,
        validate: bool = True,
        max_output: int = MAX_OUTPUT_LENGTH,
    ):
        self.container = container
        self.limits = limits or ResourceLimits()
        self.validate = validate
        self.max_output = max_output
    
    def execute(
        self,
        code: str,
        language: str = "python",
        workdir: str = "/workspace",
    ) -> ExecutionResult:
        """Führt Code im Container aus."""
        start_time = time.time()
        
        # 1. Validierung
        if self.validate:
            is_valid, error, warnings = validate_code(code, language)
            if not is_valid:
                return ExecutionResult(
                    exit_code=-1,
                    stdout="",
                    stderr=error or "Validation failed",
                    error=error,
                    language=language,
                )
            for warning in warnings:
                log_info(f"Validation warning: {warning}")
        
        # 2. Sprach-Config
        lang_config = get_language_config(language)
        filename = lang_config["file"]
        exec_cmd = lang_config["cmd"]
        
        # 3. Code in Container schreiben
        try:
            self._write_code_to_container(code, filename, workdir)
        except Exception as e:
            log_error(f"Failed to write code: {e}")
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=f"Failed to write code: {e}",
                error=str(e),
                language=language,
            )
        
        # 4. Mit Timeout ausführen
        try:
            if self.limits and self.limits.timeout > 0:
                exec_cmd = self.limits.get_timeout_command(exec_cmd)
            
            log_info(f"Executing: {' '.join(exec_cmd)}")
            
            exec_result = self.container.exec_run(
                exec_cmd,
                workdir=workdir,
                demux=True,
            )
            
            stdout = ""
            stderr = ""
            
            if exec_result.output:
                if exec_result.output[0]:
                    stdout = exec_result.output[0].decode("utf-8", errors="replace")
                if exec_result.output[1]:
                    stderr = exec_result.output[1].decode("utf-8", errors="replace")
            
            stdout = sanitize_output(stdout, self.max_output)
            stderr = sanitize_output(stderr, self.max_output)
            
            timed_out = exec_result.exit_code == 124
            duration_ms = int((time.time() - start_time) * 1000)
            
            return ExecutionResult(
                exit_code=exec_result.exit_code,
                stdout=stdout,
                stderr=stderr,
                timed_out=timed_out,
                duration_ms=duration_ms,
                language=language,
            )
            
        except Exception as e:
            log_error(f"Execution failed: {e}")
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                error=str(e),
                duration_ms=int((time.time() - start_time) * 1000),
                language=language,
            )
    
    def _write_code_to_container(
        self,
        code: str,
        filename: str,
        workdir: str = "/workspace",
    ) -> None:
        """Schreibt Code als Datei in den Container."""
        tar_stream = io.BytesIO()
        
        with tarfile.open(fileobj=tar_stream, mode='w') as tar:
            code_bytes = code.encode('utf-8')
            tarinfo = tarfile.TarInfo(name=filename)
            tarinfo.size = len(code_bytes)
            tarinfo.mode = 0o644
            tar.addfile(tarinfo, io.BytesIO(code_bytes))
        
        tar_stream.seek(0)
        self.container.put_archive(workdir, tar_stream)
        log_info(f"Code written: {filename} ({len(code)} chars)")
    
    def run_command(
        self,
        command: str,
        workdir: str = "/workspace",
    ) -> ExecutionResult:
        """Führt einen Shell-Befehl aus."""
        start_time = time.time()
        
        if self.validate:
            is_valid, error, warnings = validate_code(command, "bash")
            if not is_valid:
                return ExecutionResult(
                    exit_code=-1,
                    stdout="",
                    stderr=error or "Command validation failed",
                    error=error,
                    language="bash",
                )
        
        try:
            cmd = command
            if self.limits and self.limits.timeout > 0:
                cmd = f"timeout {self.limits.timeout} {command}"
            
            exec_result = self.container.exec_run(
                cmd,
                workdir=workdir,
                demux=True,
            )
            
            stdout = ""
            stderr = ""
            
            if exec_result.output:
                if exec_result.output[0]:
                    stdout = exec_result.output[0].decode("utf-8", errors="replace")
                if exec_result.output[1]:
                    stderr = exec_result.output[1].decode("utf-8", errors="replace")
            
            stdout = sanitize_output(stdout, self.max_output)
            stderr = sanitize_output(stderr, self.max_output)
            
            return ExecutionResult(
                exit_code=exec_result.exit_code,
                stdout=stdout,
                stderr=stderr,
                timed_out=exec_result.exit_code == 124,
                duration_ms=int((time.time() - start_time) * 1000),
                language="bash",
            )
            
        except Exception as e:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                error=str(e),
                duration_ms=int((time.time() - start_time) * 1000),
                language="bash",
            )


# ============================================================
# CONVENIENCE FUNCTION
# ============================================================

def execute_code_in_container(
    container,
    code: str,
    language: str = "python",
    limits: Optional[ResourceLimits] = None,
) -> ExecutionResult:
    """Convenience-Funktion für Code-Ausführung."""
    executor = CodeExecutor(container, limits)
    return executor.execute(code, language)
