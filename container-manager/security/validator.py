# security/validator.py
"""
Command & Code Validation.

Prüft Befehle und Code auf gefährliche Patterns
bevor sie ausgeführt werden.
"""

import re
from typing import Tuple, List, Optional
from dataclasses import dataclass

# Default hier
MAX_CODE_LENGTH = 100000  # 100KB


class CommandValidationError(Exception):
    """Fehler bei der Command-Validierung."""
    pass


# ============================================================
# BLOCKED PATTERNS
# ============================================================

# Regex-Patterns für gefährliche Befehle
BLOCKED_PATTERNS: List[Tuple[str, str]] = [
    # Destruktive Befehle
    (r"rm\s+(-[a-zA-Z]*)?(\s+)?(\/|~)", "Löschen von Root/Home"),
    (r"rm\s+-rf\s+/", "Rekursives Löschen von Root"),
    (r"rmdir\s+/", "Löschen von Root-Verzeichnissen"),
    
    # Fork-Bombs
    (r":\(\)\s*\{\s*:\|:&", "Fork-Bomb (Bash)"),
    (r"fork\s*while\s*fork", "Fork-Bomb (Ruby)"),
    (r"while\s*True.*os\.fork", "Fork-Bomb (Python)"),
    
    # Disk-Angriffe
    (r"dd\s+if=/dev/(zero|random|urandom)", "Disk-Fill Angriff"),
    (r">\s*/dev/sd[a-z]", "Direct Disk Write"),
    (r"mkfs\.", "Filesystem Format"),
    
    # Netzwerk-Angriffe (falls Netzwerk erlaubt)
    (r"nc\s+-l", "Netcat Listen Mode"),
    (r"ncat.*-e\s*/bin", "Reverse Shell"),
    
    # System-Manipulation
    (r"/etc/passwd", "Zugriff auf Passwort-Datei"),
    (r"/etc/shadow", "Zugriff auf Shadow-Datei"),
    (r"/etc/sudoers", "Zugriff auf Sudoers"),
    (r"chmod\s+[0-7]*777", "Chmod 777"),
    (r"chown\s+root", "Chown zu Root"),
    
    # Crypto-Mining Patterns
    (r"stratum\+tcp", "Mining Pool Connection"),
    (r"xmrig|cgminer|bfgminer", "Crypto Miner"),
    
    # Kernel-Manipulation
    (r"/proc/sys", "Kernel Parameter Manipulation"),
    (r"sysctl\s+-w", "Sysctl Write"),
    (r"insmod|modprobe", "Kernel Module Loading"),
]

# Komplett blockierte Befehle (am Anfang des Commands)
BLOCKED_COMMANDS: List[str] = [
    "shutdown", "reboot", "halt", "poweroff", "init",
    "systemctl", "service",
    "mount", "umount",
    "iptables", "ip6tables", "nft",
    "useradd", "userdel", "usermod",
    "groupadd", "groupdel", "groupmod",
    "passwd", "chpasswd",
    "su", "sudo",
    "docker", "podman", "kubectl",
    "crontab",
]

# Warnungen (erlaubt, aber geloggt)
WARNING_PATTERNS: List[Tuple[str, str]] = [
    (r"subprocess", "Subprocess-Nutzung"),
    (r"os\.system", "OS System Call"),
    (r"eval\s*\(", "Eval-Nutzung"),
    (r"exec\s*\(", "Exec-Nutzung"),
    (r"socket\.", "Socket-Nutzung"),
    (r"requests\.", "HTTP Requests"),
    (r"urllib", "URL Library"),
]


# ============================================================
# VALIDATION FUNCTIONS
# ============================================================

def validate_command(command: str) -> Tuple[bool, Optional[str]]:
    """
    Validiert einen Shell-Befehl.
    
    Args:
        command: Der zu prüfende Befehl
        
    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
    """
    if not command or not command.strip():
        return False, "Leerer Befehl"
    
    cmd_lower = command.lower().strip()
    
    # Prüfe blockierte Patterns
    for pattern, reason in BLOCKED_PATTERNS:
        if re.search(pattern, cmd_lower, re.IGNORECASE):
            return False, f"Blockiert: {reason}"
    
    # Prüfe blockierte Befehle (erstes Wort)
    first_word = cmd_lower.split()[0] if cmd_lower.split() else ""
    # Entferne Pfad falls vorhanden
    first_word = first_word.split("/")[-1]
    
    if first_word in BLOCKED_COMMANDS:
        return False, f"Befehl '{first_word}' ist nicht erlaubt"
    
    return True, None


def validate_code(code: str, language: str = "python") -> Tuple[bool, Optional[str], List[str]]:
    """
    Validiert Code vor Ausführung.
    
    Args:
        code: Der zu prüfende Code
        language: Programmiersprache
        
    Returns:
        Tuple[bool, Optional[str], List[str]]: (is_valid, error, warnings)
    """
    warnings = []
    
    if not code or not code.strip():
        return False, "Leerer Code", warnings
    
    # Größen-Check
    if len(code) > MAX_CODE_LENGTH:
        return False, f"Code zu groß ({len(code)} > {MAX_CODE_LENGTH} bytes)", warnings
    
    code_lower = code.lower()
    
    # Shell-Sprachen: Volle Command-Validierung
    if language in ["bash", "sh", "shell"]:
        # Jede Zeile validieren
        for line_num, line in enumerate(code.split("\n"), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            is_valid, error = validate_command(line)
            if not is_valid:
                return False, f"Zeile {line_num}: {error}", warnings
    
    # Pattern-Checks für alle Sprachen
    for pattern, reason in BLOCKED_PATTERNS:
        if re.search(pattern, code_lower, re.IGNORECASE):
            return False, f"Blockiertes Pattern: {reason}", warnings
    
    # Warnungen sammeln (blockiert nicht)
    for pattern, reason in WARNING_PATTERNS:
        if re.search(pattern, code_lower, re.IGNORECASE):
            warnings.append(f"Warnung: {reason}")
    
    return True, None, warnings


def sanitize_output(output: str, max_length: int = 10000) -> str:
    """
    Bereinigt Container-Output.
    
    - Kürzt auf max_length
    - Entfernt sensitive Patterns
    
    Args:
        output: Roher Output
        max_length: Maximale Länge
        
    Returns:
        Bereinigter Output
    """
    if not output:
        return ""
    
    # Kürzen
    if len(output) > max_length:
        output = output[:max_length] + f"\n... (gekürzt, {len(output)} total)"
    
    # Sensitive Patterns entfernen
    sensitive_patterns = [
        (r"password[=:]\s*\S+", "password=***"),
        (r"api[_-]?key[=:]\s*\S+", "api_key=***"),
        (r"token[=:]\s*\S+", "token=***"),
        (r"secret[=:]\s*\S+", "secret=***"),
    ]
    
    for pattern, replacement in sensitive_patterns:
        output = re.sub(pattern, replacement, output, flags=re.IGNORECASE)
    
    return output


@dataclass
class ValidationResult:
    """Ergebnis einer Validierung."""
    is_valid: bool
    error: Optional[str] = None
    warnings: List[str] = None
    risk_level: str = "low"
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []
    
    def to_dict(self):
        return {
            "is_valid": self.is_valid,
            "error": self.error,
            "warnings": self.warnings,
            "risk_level": self.risk_level,
        }


def full_validation(code: str, language: str) -> ValidationResult:
    """
    Führt vollständige Validierung durch.
    
    Args:
        code: Zu validierender Code
        language: Programmiersprache
        
    Returns:
        ValidationResult
    """
    is_valid, error, warnings = validate_code(code, language)
    
    # Risiko-Level berechnen
    risk_level = "low"
    if len(warnings) > 0:
        risk_level = "medium"
    if len(warnings) > 3:
        risk_level = "high"
    if not is_valid:
        risk_level = "blocked"
    
    return ValidationResult(
        is_valid=is_valid,
        error=error,
        warnings=warnings,
        risk_level=risk_level,
    )
