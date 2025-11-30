from datetime import datetime
from config import LOG_LEVEL

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
    ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
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
    print(f"[WARN] {msg}")