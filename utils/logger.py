import os
from datetime import datetime, timezone

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]


def _should_log(level: str) -> bool:
    try:
        cur = LEVELS.index(LOG_LEVEL)
        want = LEVELS.index(level)
        return want >= cur
    except ValueError:
        return True


def _log(level: str, msg: str):
    if not _should_log(level):
        return
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    print(f"[{ts}] [{level}] {msg}")


def log_debug(msg: str):
    _log("DEBUG", msg)


def log_info(msg: str):
    _log("INFO", msg)


def log_warning(msg: str):
    _log("WARNING", msg)


def log_error(msg: str):
    _log("ERROR", msg)
    
def log_warn(msg: str):
    log_warning(msg)
