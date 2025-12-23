# config.py
"""
Container-Manager Konfiguration.

Alle Einstellungen zentral an einem Ort.
Kann über Umgebungsvariablen überschrieben werden.
"""

import os

# ============================================================
# PFADE
# ============================================================

REGISTRY_PATH = os.environ.get("REGISTRY_PATH", "/app/container_defs/registry.yaml")
CONTAINERS_PATH = os.environ.get("CONTAINERS_PATH", "/app/container_defs")

# ============================================================
# OUTPUT LIMITS
# ============================================================

MAX_OUTPUT_LENGTH = int(os.environ.get("MAX_OUTPUT_LENGTH", "10000"))
MAX_CODE_LENGTH = int(os.environ.get("MAX_CODE_LENGTH", "100000"))  # 100KB

# ============================================================
# SESSION MANAGEMENT
# ============================================================

DEFAULT_SESSION_TTL = int(os.environ.get("DEFAULT_SESSION_TTL", "300"))  # 5 Minuten
MAX_SESSION_TTL = int(os.environ.get("MAX_SESSION_TTL", "3600"))  # 1 Stunde
CLEANUP_INTERVAL = int(os.environ.get("CLEANUP_INTERVAL", "30"))  # Sekunden

# ============================================================
# RESOURCE DEFAULTS
# ============================================================

DEFAULT_MEMORY_LIMIT = os.environ.get("DEFAULT_MEMORY_LIMIT", "512m")
DEFAULT_CPU_LIMIT = float(os.environ.get("DEFAULT_CPU_LIMIT", "1.0"))
DEFAULT_PIDS_LIMIT = int(os.environ.get("DEFAULT_PIDS_LIMIT", "100"))
DEFAULT_DISK_LIMIT = os.environ.get("DEFAULT_DISK_LIMIT", "100m")

# ============================================================
# TIMEOUTS
# ============================================================

DEFAULT_EXECUTION_TIMEOUT = int(os.environ.get("DEFAULT_EXECUTION_TIMEOUT", "60"))
MAX_EXECUTION_TIMEOUT = int(os.environ.get("MAX_EXECUTION_TIMEOUT", "300"))
CONTAINER_STOP_TIMEOUT = int(os.environ.get("CONTAINER_STOP_TIMEOUT", "10"))

# ============================================================
# RATE LIMITING (für zukünftige Nutzung)
# ============================================================

RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS", "30"))
RATE_LIMIT_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW", "60"))  # Sekunden

# ============================================================
# TTYD CONFIGURATION
# ============================================================

TTYD_PORT = int(os.environ.get("TTYD_PORT", "7681"))
TTYD_COMMAND = os.environ.get("TTYD_COMMAND", "ttyd -W -p 7681 bash")

# ============================================================
# SECURITY DEFAULTS
# ============================================================

DEFAULT_NETWORK_MODE = os.environ.get("DEFAULT_NETWORK_MODE", "none")
DEFAULT_READ_ONLY = os.environ.get("DEFAULT_READ_ONLY", "false").lower() == "true"

# Capabilities die standardmäßig entfernt werden
DEFAULT_CAP_DROP = ["ALL"]
DEFAULT_CAP_ADD = []

# Security Options
DEFAULT_SECURITY_OPT = ["no-new-privileges:true"]

# ============================================================
# LOGGING
# ============================================================

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOG_PREFIX = "[ContainerManager]"

def log(message: str, level: str = "INFO") -> None:
    """Einfaches Logging mit Prefix."""
    print(f"{LOG_PREFIX} [{level}] {message}")

def log_info(message: str) -> None:
    log(message, "INFO")

def log_error(message: str) -> None:
    log(message, "ERROR")

def log_warning(message: str) -> None:
    log(message, "WARN")

def log_debug(message: str) -> None:
    if LOG_LEVEL == "DEBUG":
        log(message, "DEBUG")
