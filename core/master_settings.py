import json
import os
from typing import Any, Dict


def get_master_settings() -> Dict[str, Any]:
    """Load Master Orchestrator settings."""
    settings_file = "/tmp/settings_master.json"
    default = {
        "enabled": True,
        "use_thinking_layer": False,
        "max_loops": 10,
        "completion_threshold": 2,
    }
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default
