# core/persona.py
"""
Persona Manager v3.0 - TRION Adaptive Persona System

Unterstützt:
- Neue Sektionen: CAPABILITIES, TOOL_AWARENESS, ONBOARDING, ADAPTATION
- Adaptive Greeting (new user vs known user)
- Dynamic tool injection
- Multiple Personas (.txt Files)
"""

import re
from pathlib import Path
from typing import Dict, Any, Optional, List
from utils.logger import log_info, log_error, log_warn

PERSONAS_DIR = Path(__file__).parent.parent / "personas"
LEGACY_CONFIG_PATH = Path(__file__).parent.parent / "config" / "persona.yaml"

_persona_instance: Optional['Persona'] = None
_active_persona_name: str = "default"


class Persona:
    """Repräsentiert die Persona des Assistenten."""
    
    def __init__(self, config: Dict[str, Any]):
        self.name = config.get("name", "TRION")
        self.role = config.get("role", "Adaptive AI Assistant")
        self.language = config.get("language", "auto-detect")
        self.user_name = config.get("user_name", "unknown")
        self.user_context = config.get("user_context", [])
        self.personality = config.get("personality", [])
        self.style = config.get("style", "freundlich-professionell")
        self.verbosity = config.get("verbosity", "so kurz wie möglich, so lang wie nötig")
        self.core_rules = config.get("core_rules", [])
        self.privacy_rules = config.get("privacy_rules", [])
        self.greeting = config.get("greeting", "Hey! Ich bin TRION.")
        self.greeting_known = config.get("greeting_known", "Hey {user_name}! Was kann ich für dich tun?")
        self.farewell = config.get("farewell", "Bis später! 👋")
        # New v3 sections
        self.capabilities = config.get("capabilities", [])
        self.tool_awareness = config.get("tool_awareness", [])
        self.onboarding = config.get("onboarding", [])
        self.adaptation = config.get("adaptation", [])
        self.core_philosophy = config.get("core_philosophy", [])
    
    def build_system_prompt(self, dynamic_context=None, user_profile=None):
        """Baut den System-Prompt. Passt sich an User-Profil an."""
        
        parts = []
        
        # === IDENTITÄT ===
        parts.append(f"Du bist {self.name}, {self.role}.")
        if self.core_philosophy:
            for p in self.core_philosophy:
                parts.append(p)
        
        # === USER KONTEXT (adaptiv) ===
        if user_profile and user_profile.get("name"):
            # Known user
            name = user_profile.get("name", "")
            parts.append(f"\n### USER-PROFIL:")
            parts.append(f"Name: {name}")
            if user_profile.get("profession"):
                parts.append(f"Beruf: {user_profile['profession']}")
            if user_profile.get("interests"):
                parts.append(f"Interessen: {user_profile['interests']}")
            if user_profile.get("language"):
                parts.append(f"Sprache: {user_profile['language']}")
            if user_profile.get("tone"):
                parts.append(f"Bevorzugter Ton: {user_profile['tone']}")
            parts.append(f"Sprich {name} direkt mit 'du' an.")
            if self.adaptation:
                for a in self.adaptation:
                    parts.append(f"- {a}")
        else:
            # Unknown user → Onboarding
            if self.onboarding:
                parts.append("\n### ONBOARDING (Neuer User):")
                for o in self.onboarding:
                    parts.append(f"- {o}")
        
        # === PERSÖNLICHKEIT ===
        if self.personality:
            traits = ", ".join(self.personality)
            parts.append(f"\nDeine Persönlichkeit: {traits}.")
        
        # === STIL ===
        parts.append(f"\nTon: {self.style}.")
        parts.append(f"Antwortlänge: {self.verbosity}.")
        
        # === FÄHIGKEITEN ===
        if self.capabilities:
            parts.append("\n### DEINE FÄHIGKEITEN:")
            for cap in self.capabilities:
                parts.append(f"- {cap}")
        
        # === TOOL-ZUGRIFF (dynamisch) ===
        if self.tool_awareness:
            parts.append("\n### TOOL-ZUGRIFF:")
            for ta in self.tool_awareness:
                parts.append(f"- {ta}")
        
        # Dynamic Tools von MCP
        if dynamic_context and dynamic_context.get("tools"):
            tools = dynamic_context["tools"]
            if tools:
                parts.append("\n### VERFÜGBARE TOOLS (live vom System geladen):")
                for tool in tools:
                    name = tool.get("name", "unknown")
                    desc = tool.get("description", "")
                    mcp = tool.get("mcp", "")
                    parts.append(f"  • {name} [{mcp}]: {desc}")
                parts.append("")
                parts.append("WICHTIG: Wenn du ein Tool nutzen sollst, wird das System es für dich aufrufen.")
                parts.append("Du bekommst das Ergebnis und formulierst daraus deine Antwort.")
                parts.append("Sage NIEMALS 'Ich habe X gemacht' ohne ein echtes Tool-Ergebnis!")

                # Container Commander: Ressourcen-Hinweis
                container_tools = [t for t in tools if t.get("mcp") == "container-commander"]
                if container_tools:
                    parts.append("")
                    parts.append("### CONTAINER-MANAGEMENT:")
                    parts.append("Sei ressourcenschonend! Starte nur Container die du brauchst.")
                    parts.append("Beende Container SOFORT nach Erledigung mit stop_container.")
                    parts.append("Prüfe container_stats regelmäßig — bei efficiency_level red → stoppen.")
                    parts.append("Nutze die kleinsten Resource-Limits die ausreichen.")
                
                # TRION Home: Persistentes Zuhause
                home_tools = [t for t in tools if t.get("name", "").startswith("home_")]
                if home_tools:
                    parts.append("")
                    parts.append("### DEIN ZUHAUSE:")
                    parts.append("Du hast ein persistentes Zuhause im Container 'trion-home'.")
                    parts.append("Nutze es NATÜRLICH — erkläre dem User NICHT wie die Tools funktionieren!")
                    parts.append("  • 'Merk dir das' → home_write nutzen, dann bestätigen ('Hab ich notiert!')")
                    parts.append("  • 'Was hattest du notiert?' → home_read nutzen, Inhalt zusammenfassen")
                    parts.append("  • 'Zeig mir meine Dateien' → home_list nutzen")
                    parts.append("Deine Dateien überleben Neustarts. Speichere wichtige Infos dort!")
        
        # === REGELN ===
        if self.core_rules:
            parts.append("\n### REGELN:")
            for i, rule in enumerate(self.core_rules, 1):
                parts.append(f"{i}. {rule}")
        
        # === PRIVACY ===
        if self.privacy_rules:
            parts.append("\n### SICHERHEIT:")
            for rule in self.privacy_rules:
                parts.append(f"- {rule}")
        
        return "\n".join(parts)
    
    def get_greeting(self, user_profile=None):
        """Gibt passenden Greeting zurück."""
        if user_profile and user_profile.get("name"):
            return self.greeting_known.replace("{user_name}", user_profile["name"])
        return self.greeting
    
    def __repr__(self):
        return f"<Persona: {self.name}>"


# ============================================================
# PARSER
# ============================================================

def parse_persona_txt(content: str) -> Dict[str, Any]:
    """Parse .txt Persona format into dict."""
    config = {
        "name": "TRION", "role": "Adaptive AI Assistant",
        "language": "auto-detect", "user_name": "unknown",
        "user_context": [], "personality": [], "style": "freundlich-professionell",
        "verbosity": "so kurz wie möglich, so lang wie nötig",
        "core_rules": [], "privacy_rules": [],
        "greeting": "Hey!", "greeting_known": "Hey {user_name}!",
        "farewell": "Bis später! 👋",
        "capabilities": [], "tool_awareness": [], "onboarding": [],
        "adaptation": [], "core_philosophy": []
    }
    
    current_section = None
    
    for line in content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        if line.startswith('[') and line.endswith(']'):
            current_section = line[1:-1].upper()
            continue
        
        # Key-value sections
        if current_section == "IDENTITY":
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower()
                value = value.strip()
                if key == "name": config["name"] = value
                elif key == "role": config["role"] = value
                elif key == "language": config["language"] = value
                elif key == "user_name": config["user_name"] = value
        
        elif current_section == "STYLE":
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower()
                value = value.strip()
                if key == "tone": config["style"] = value
                elif key == "verbosity": config["verbosity"] = value
        
        elif current_section == "GREETINGS":
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower()
                value = value.strip()
                if key == "greeting" or key == "greeting_new": config["greeting"] = value
                elif key == "greeting_known": config["greeting_known"] = value
                elif key == "farewell": config["farewell"] = value
        
        # List sections (- item)
        elif current_section == "USER_CONTEXT" and line.startswith('-'):
            config["user_context"].append(line[1:].strip())
        elif current_section == "PERSONALITY" and line.startswith('-'):
            config["personality"].append(line[1:].strip())
        elif current_section == "PRIVACY" and line.startswith('-'):
            config["privacy_rules"].append(line[1:].strip())
        elif current_section == "CAPABILITIES" and line.startswith('-'):
            config["capabilities"].append(line[1:].strip())
        elif current_section == "TOOL_AWARENESS" and line.startswith('-'):
            config["tool_awareness"].append(line[1:].strip())
        elif current_section == "ONBOARDING" and line.startswith('-'):
            config["onboarding"].append(line[1:].strip())
        elif current_section == "ADAPTATION" and line.startswith('-'):
            config["adaptation"].append(line[1:].strip())
        elif current_section == "CORE_PHILOSOPHY" and line.startswith('-'):
            config["core_philosophy"].append(line[1:].strip())
        
        # Numbered rules
        elif current_section == "RULES":
            clean = re.sub(r'^\d+\.\s*', '', line)
            if clean: config["core_rules"].append(clean)
    
    return config


# ============================================================
# PERSONA MANAGEMENT
# ============================================================

def list_personas() -> List[str]:
    """List all available persona files."""
    if not PERSONAS_DIR.exists():
        return ["default"]
    personas = [f.stem for f in PERSONAS_DIR.glob("*.txt")]
    if "default" not in personas:
        personas.insert(0, "default")
    return sorted(personas)


def load_persona(name: str = "default") -> Persona:
    """Load persona by name. Fallback chain: .txt → .yaml → empty."""
    global _persona_instance
    
    txt_path = PERSONAS_DIR / f"{name}.txt"
    if txt_path.exists():
        try:
            with open(txt_path, "r", encoding="utf-8") as f:
                content = f.read()
            config = parse_persona_txt(content)
            log_info(f"[Persona] Loaded: {name}")
            _persona_instance = Persona(config)
            return _persona_instance
        except Exception as e:
            log_error(f"[Persona] Error loading {name}.txt: {e}")
    
    # Legacy YAML fallback
    if LEGACY_CONFIG_PATH.exists():
        try:
            import yaml
            with open(LEGACY_CONFIG_PATH, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            log_warn(f"[Persona] Using legacy persona.yaml")
            _persona_instance = Persona(config)
            return _persona_instance
        except Exception as e:
            log_error(f"[Persona] Error loading YAML: {e}")
    
    log_error(f"[Persona] No valid persona, using defaults")
    _persona_instance = Persona({})
    return _persona_instance


def save_persona(name: str, content: str) -> bool:
    """Save persona file."""
    safe_name = re.sub(r'[^\w\-]', '_', name)
    if not PERSONAS_DIR.exists():
        PERSONAS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(PERSONAS_DIR / f"{safe_name}.txt", "w", encoding="utf-8") as f:
            f.write(content)
        log_info(f"[Persona] Saved: {safe_name}.txt")
        return True
    except Exception as e:
        log_error(f"[Persona] Error saving {safe_name}.txt: {e}")
        return False


def delete_persona(name: str) -> bool:
    """Delete persona (cannot delete 'default')."""
    if name == "default":
        log_error("[Persona] Cannot delete default persona")
        return False
    path = PERSONAS_DIR / f"{name}.txt"
    if not path.exists():
        return False
    try:
        path.unlink()
        log_info(f"[Persona] Deleted: {name}.txt")
        return True
    except Exception as e:
        log_error(f"[Persona] Error deleting: {e}")
        return False


def switch_persona(name: str) -> Persona:
    """Switch to different persona (hot-reload)."""
    global _active_persona_name, _persona_instance
    log_info(f"[Persona] Switching: '{_active_persona_name}' → '{name}'")
    _persona_instance = None
    _active_persona_name = name
    return load_persona(name)


def get_active_persona_name() -> str:
    """Return currently active persona name."""
    return _active_persona_name


def reload_persona() -> Persona:
    """Reload current persona (hot-reload)."""
    return switch_persona(_active_persona_name)


def get_persona() -> Persona:
    """Get current persona instance (loads if needed)."""
    global _persona_instance
    if _persona_instance is None:
        return load_persona(_active_persona_name)
    return _persona_instance
