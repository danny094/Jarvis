"""
Settings Manager
Handles runtime configuration overrides and persistence.
"""
import os
import json
from pathlib import Path
from typing import Dict, Any, Optional

SETTINGS_FILE = Path("config/settings.json")

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
        if SETTINGS_FILE.exists():
            try:
                self.settings = json.loads(SETTINGS_FILE.read_text())
            except Exception as e:
                print(f"[Settings] Failed to load settings: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get setting with fallback to env var (via default arg usually)."""
        return self.settings.get(key, default)
    
    def set(self, key: str, value: Any):
        """Set and persist a setting."""
        self.settings[key] = value
        self._save()
        
    def _save(self):
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(self.settings, indent=2))

# Global accessor
settings = SettingsManager()
