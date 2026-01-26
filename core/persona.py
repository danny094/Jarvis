# core/persona.py
"""
Persona Manager - Multi-Persona System mit .txt Support
Version: 2.0.0 (Refactored 2026-01-04)

Unterstützt:
- Multiple Personas (.txt Files)
- Hot-Reload / Switching
- Protected default Persona
- Backward compatibility mit persona.yaml
"""

import re
from pathlib import Path
from typing import Dict, Any, Optional, List
from utils.logger import log_info, log_error, log_warn

# Paths
PERSONAS_DIR = Path(__file__).parent.parent / "personas"
LEGACY_CONFIG_PATH = Path(__file__).parent.parent / "config" / "persona.yaml"

# Global State
_persona_instance: Optional['Persona'] = None
_active_persona_name: str = "default"


class Persona:
    """Repräsentiert die Persona des Assistenten."""
    
    def __init__(self, config: Dict[str, Any]):
        self.name = config.get("name", "Assistent")
        self.role = config.get("role", "AI Assistent")
        self.language = config.get("language", "english")
        self.user_name = config.get("user_name", "User")
        self.user_context = config.get("user_context", [])
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
        
        # WICHTIG: Wer ist der User?
        prompt_parts.append(f"\n### WER IST DER USER:")
        prompt_parts.append(f"Der User heißt {self.user_name}.")
        if self.user_context:
            for ctx in self.user_context:
                prompt_parts.append(f"- {ctx}")
        
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


# ============================================================
# PARSER FUNCTIONS
# ============================================================

def parse_persona_txt(content: str) -> Dict[str, Any]:
    """
    Parse .txt Persona format into dict.
    
    Format:
        [IDENTITY]
        name: Value
        
        [PERSONALITY]
        - trait1
        - trait2
        
        [RULES]
        1. Rule one
        2. Rule two
    
    Returns:
        Dict compatible with Persona class
    """
    config = {
        "name": "Unknown",
        "role": "AI Assistant",
        "language": "english",
        "user_name": "User",
        "user_context": [],
        "personality": [],
        "style": "freundlich",
        "core_rules": [],
        "privacy_rules": [],
        "greeting": "Hallo!",
        "farewell": "Tschüss!"
    }
    
    # Split into sections
    current_section = None
    
    for line in content.split('\n'):
        line = line.strip()
        
        # Skip empty lines and comments
        if not line or line.startswith('#'):
            continue
        
        # Section header
        if line.startswith('[') and line.endswith(']'):
            current_section = line[1:-1].upper()
            continue
        
        # Parse content based on section
        if current_section == "IDENTITY":
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()
                
                if key == "name":
                    config["name"] = value
                elif key == "role":
                    config["role"] = value
                elif key == "language":
                    config["language"] = value
                elif key == "user_name":
                    config["user_name"] = value
        
        elif current_section == "USER_CONTEXT":
            if line.startswith('-'):
                config["user_context"].append(line[1:].strip())
        
        elif current_section == "PERSONALITY":
            if line.startswith('-'):
                config["personality"].append(line[1:].strip())
        
        elif current_section == "STYLE":
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()
                
                if key == "tone":
                    config["style"] = value
                # Ignore other style fields for now (verbosity, etc.)
        
        elif current_section == "RULES":
            # Remove numbering (1. 2. etc.)
            clean_line = re.sub(r'^\d+\.\s*', '', line)
            if clean_line:
                config["core_rules"].append(clean_line)
        
        elif current_section == "PRIVACY":
            if line.startswith('-'):
                config["privacy_rules"].append(line[1:].strip())
        
        elif current_section == "GREETINGS":
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()
                
                if key == "greeting":
                    config["greeting"] = value
                elif key == "farewell":
                    config["farewell"] = value
    
    return config


# ============================================================
# PERSONA MANAGEMENT FUNCTIONS
# ============================================================

def list_personas() -> List[str]:
    """
    List all available persona files.
    
    Returns:
        List of persona names (without .txt extension)
    """
    if not PERSONAS_DIR.exists():
        log_warn(f"[Persona] Directory not found: {PERSONAS_DIR}")
        return ["default"]
    
    personas = []
    for file in PERSONAS_DIR.glob("*.txt"):
        personas.append(file.stem)
    
    # Ensure default is always available
    if "default" not in personas:
        personas.insert(0, "default")
    
    return sorted(personas)


def load_persona(name: str = "default") -> Persona:
    """
    Load specific persona by name.
    
    Args:
        name: Persona name (without .txt)
    
    Returns:
        Persona instance
    
    Fallback order:
        1. personas/{name}.txt
        2. config/persona.yaml (legacy)
        3. Empty Persona (safe fallback)
    """
    global _persona_instance
    
    # Try loading .txt file
    txt_path = PERSONAS_DIR / f"{name}.txt"
    
    if txt_path.exists():
        try:
            with open(txt_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            config = parse_persona_txt(content)
            log_info(f"[Persona] Loaded from .txt: {name}")
            _persona_instance = Persona(config)
            return _persona_instance
        
        except Exception as e:
            log_error(f"[Persona] Error loading {name}.txt: {e}")
            # Fall through to next method
    
    # Legacy YAML fallback
    if LEGACY_CONFIG_PATH.exists():
        try:
            import yaml
            with open(LEGACY_CONFIG_PATH, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            
            log_warn(f"[Persona] Using legacy persona.yaml (migrate to .txt!)")
            _persona_instance = Persona(config)
            return _persona_instance
        
        except Exception as e:
            log_error(f"[Persona] Error loading legacy YAML: {e}")
    
    # Ultimate fallback
    log_error(f"[Persona] No valid persona found, using empty config")
    _persona_instance = Persona({})
    return _persona_instance


def save_persona(name: str, content: str) -> bool:
    """
    Save new persona file.
    
    Args:
        name: Persona name (sanitized)
        content: Raw .txt content
    
    Returns:
        True if successful, False otherwise
    
    Security:
        - Sanitizes filename
        - Creates personas/ dir if missing
        - UTF-8 encoding enforced
    """
    # Sanitize filename
    safe_name = re.sub(r'[^\w\-]', '_', name)
    
    if not PERSONAS_DIR.exists():
        PERSONAS_DIR.mkdir(parents=True, exist_ok=True)
        log_info(f"[Persona] Created directory: {PERSONAS_DIR}")
    
    file_path = PERSONAS_DIR / f"{safe_name}.txt"
    
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        log_info(f"[Persona] Saved: {safe_name}.txt")
        return True
    
    except Exception as e:
        log_error(f"[Persona] Error saving {safe_name}.txt: {e}")
        return False


def delete_persona(name: str) -> bool:
    """
    Delete persona file.
    
    Args:
        name: Persona name to delete
    
    Returns:
        True if successful, False otherwise
    
    Protection:
        - Cannot delete "default" persona
        - File must exist
    """
    # Protection: Cannot delete default
    if name == "default":
        log_error("[Persona] Cannot delete protected persona: default")
        return False
    
    file_path = PERSONAS_DIR / f"{name}.txt"
    
    if not file_path.exists():
        log_error(f"[Persona] File not found: {name}.txt")
        return False
    
    try:
        file_path.unlink()
        log_info(f"[Persona] Deleted: {name}.txt")
        return True
    
    except Exception as e:
        log_error(f"[Persona] Error deleting {name}.txt: {e}")
        return False


def switch_persona(name: str) -> Persona:
    """
    Switch to different persona (hot-reload).
    
    Args:
        name: Persona name to switch to
    
    Returns:
        New Persona instance
    
    Side Effects:
        - Updates global _active_persona_name
        - Clears _persona_instance cache
        - Triggers load_persona()
    """
    global _active_persona_name, _persona_instance
    
    log_info(f"[Persona] Switching from '{_active_persona_name}' to '{name}'")
    
    # Clear cache
    _persona_instance = None
    
    # Update active name
    _active_persona_name = name
    
    # Load new persona
    return load_persona(name)


def get_active_persona_name() -> str:
    """Return currently active persona name."""
    return _active_persona_name


def reload_persona() -> Persona:
    """
    Reload current persona (for Hot-Reload).
    Legacy function - delegates to switch_persona().
    """
    return switch_persona(_active_persona_name)


def get_persona() -> Persona:
    """
    Get current persona instance.
    Loads if not cached.
    """
    global _persona_instance
    
    if _persona_instance is None:
        return load_persona(_active_persona_name)
    
    return _persona_instance
