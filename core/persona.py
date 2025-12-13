# core/persona.py
"""
Persona Manager - Lädt und verwaltet die Persona-Konfiguration.

NEU: Lädt System-Prompt aus Markdown-Datei für einfache Anpassung.
"""

import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from utils.logger import log_info, log_error

# Pfade zur Config
CONFIG_PATH = Path(__file__).parent.parent / "config" / "persona.yaml"
SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "config" / "system_prompt.md"


class Persona:
    """Repräsentiert die Persona des Assistenten."""
    
    def __init__(self, config: Dict[str, Any]):
        self.name = config.get("name", "Assistent")
        self.role = config.get("role", "AI Assistent")
        self.language = config.get("language", "deutsch")
        self.user_name = config.get("user_name", "User")
        self.greeting = config.get("greeting", "Hallo!")
        self.farewell = config.get("farewell", "Tschüss!")
        
        # System-Prompt aus MD-Datei laden
        self._system_prompt = self._load_system_prompt()
    
    def _load_system_prompt(self) -> str:
        """Lädt den System-Prompt aus der Markdown-Datei."""
        try:
            if SYSTEM_PROMPT_PATH.exists():
                with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
                    content = f.read()
                log_info(f"[Persona] System-Prompt geladen: {len(content)} chars")
                return content
            else:
                log_error(f"[Persona] system_prompt.md nicht gefunden: {SYSTEM_PROMPT_PATH}")
                return self._fallback_prompt()
        except Exception as e:
            log_error(f"[Persona] Fehler beim Laden des System-Prompts: {e}")
            return self._fallback_prompt()
    
    def _fallback_prompt(self) -> str:
        """Fallback wenn MD-Datei nicht existiert."""
        return f"""Du bist {self.name}, {self.role}.
Du sprichst {self.language}.
Der User heißt {self.user_name}.
Sei freundlich und hilfsbereit."""
    
    def build_system_prompt(self) -> str:
        """Gibt den System-Prompt zurück."""
        return self._system_prompt
    
    def reload_prompt(self) -> str:
        """Lädt den System-Prompt neu (für Hot-Reload)."""
        self._system_prompt = self._load_system_prompt()
        return self._system_prompt
    
    def __repr__(self):
        return f"<Persona: {self.name}>"


# Singleton
_persona_instance: Optional[Persona] = None


def load_persona() -> Persona:
    """Lädt die Persona aus der Config-Datei."""
    global _persona_instance
    
    if _persona_instance is not None:
        return _persona_instance
    
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            log_info(f"[Persona] Geladen: {config.get('name', 'unknown')}")
            _persona_instance = Persona(config)
        else:
            log_error(f"[Persona] Config nicht gefunden: {CONFIG_PATH}")
            _persona_instance = Persona({})
    
    except Exception as e:
        log_error(f"[Persona] Fehler beim Laden: {e}")
        _persona_instance = Persona({})
    
    return _persona_instance


def reload_persona() -> Persona:
    """Lädt die Persona neu (für Hot-Reload)."""
    global _persona_instance
    _persona_instance = None
    return load_persona()


def get_persona() -> Persona:
    """Gibt die aktuelle Persona zurück."""
    return load_persona()
