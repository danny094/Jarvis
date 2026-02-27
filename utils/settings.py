"""
Settings Manager
Handles runtime configuration overrides and persistence.
"""
import os
import json
from pathlib import Path
from typing import Dict, Any, Optional


def _candidate_settings_files() -> list[Path]:
    """
    Resolve candidate locations for persisted overrides.
    Order matters:
    1) Explicit env override
    2) Writable runtime volume in containers
    3) Repo-local fallback for dev runs
    """
    raw_candidates = []
    env_file = os.getenv("JARVIS_SETTINGS_FILE") or os.getenv("SETTINGS_FILE")
    if env_file:
        raw_candidates.append(env_file)
    raw_candidates.extend([
        "/app/data/settings.json",
        "config/settings.json",
    ])

    unique: list[Path] = []
    seen = set()
    for raw in raw_candidates:
        p = Path(raw).expanduser()
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique

class SettingsManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SettingsManager, cls).__new__(cls)
            cls._instance._load()
        return cls._instance
    
    def __init__(self):
        # Already initialized in __new__
        pass
        
    def _load(self):
        self.settings = {}
        self._settings_path = _candidate_settings_files()[0]
        for candidate in _candidate_settings_files():
            if not candidate.exists():
                continue
            try:
                self.settings = json.loads(candidate.read_text())
                self._settings_path = candidate
                break
            except Exception as e:
                print(f"[Settings] Failed to load settings from {candidate}: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get setting with fallback to env var (via default arg usually)."""
        return self.settings.get(key, default)
    
    def set(self, key: str, value: Any):
        """Set and persist a setting."""
        self.settings[key] = value
        self._save()
        
    def _save(self):
        payload = json.dumps(self.settings, indent=2)
        candidates = [self._settings_path]
        candidates.extend([p for p in _candidate_settings_files() if p != self._settings_path])

        last_error = None
        for path in candidates:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(payload)
                self._settings_path = path
                return
            except Exception as e:
                last_error = e

        raise RuntimeError(f"Failed to persist settings to any candidate path: {last_error}")

# Global accessor
settings = SettingsManager()
