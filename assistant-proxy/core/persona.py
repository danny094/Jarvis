# core/persona.py
"""
Persona Manager - Lädt und verwaltet die Persona-Konfiguration.
"""

import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from utils.logger import log_info, log_error

# Pfad zur Config
CONFIG_PATH = Path(__file__).parent.parent / "config" / "persona.yaml"


class Persona:
    """Repräsentiert die Persona des Assistenten."""
    
    def __init__(self, config: Dict[str, Any]):
        self.name = config.get("name", "Assistent")
        self.role = config.get("role", "AI Assistent")
        self.language = config.get("language", "deutsch")
        self.personality = config.get("personality", [])
        self.style = config.get("style", "freundlich")
        self.core_rules = config.get("core_rules", [])
        self.privacy_rules = config.get("privacy_rules", [])
        self.greeting = config.get("greeting", "Hallo!")
        self.farewell = config.get("farewell", "Tschüss!")
    
    def build_system_prompt(self) -> str:
        """Erstellt den System-Prompt basierend auf der Persona."""
        
        prompt_parts = []
        
        # Identität
        prompt_parts.append(f"Du bist {self.name}, {self.role}.")
        prompt_parts.append(f"Du sprichst {self.language}.")
        prompt_parts.append(f"Dein Stil ist: {self.style}.")
        
        # Persönlichkeit
        if self.personality:
            traits = ", ".join(self.personality)
            prompt_parts.append(f"\nDeine Persönlichkeit: {traits}.")
        
        # Kern-Regeln
        if self.core_rules:
            prompt_parts.append("\n### WICHTIGE REGELN:")
            for i, rule in enumerate(self.core_rules, 1):
                prompt_parts.append(f"{i}. {rule}")
        
        # Privacy-Regeln
        if self.privacy_rules:
            prompt_parts.append("\n### SICHERHEIT:")
            for rule in self.privacy_rules:
                prompt_parts.append(f"- {rule}")
        
        return "\n".join(prompt_parts)
    
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
