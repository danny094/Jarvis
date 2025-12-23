# languages/config.py
"""
Language Configuration für Code-Ausführung.

Definiert welche Sprachen unterstützt werden und
wie sie ausgeführt werden.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class LanguageSpec:
    """Spezifikation für eine Programmiersprache."""
    name: str
    file_extension: str
    interpreter: str
    interpreter_path: str = "/workspace"
    aliases: List[str] = None
    
    def __post_init__(self):
        if self.aliases is None:
            self.aliases = []
    
    @property
    def filename(self) -> str:
        return f"code{self.file_extension}"
    
    @property
    def filepath(self) -> str:
        return f"{self.interpreter_path}/{self.filename}"
    
    @property
    def command(self) -> List[str]:
        return [self.interpreter, self.filepath]


# ============================================================
# LANGUAGE DEFINITIONS
# ============================================================

LANGUAGES: Dict[str, LanguageSpec] = {
    "python": LanguageSpec(
        name="Python",
        file_extension=".py",
        interpreter="python",
        aliases=["py", "python3", "py3"],
    ),
    "bash": LanguageSpec(
        name="Bash",
        file_extension=".sh",
        interpreter="bash",
        aliases=["sh", "shell"],
    ),
    "javascript": LanguageSpec(
        name="JavaScript",
        file_extension=".js",
        interpreter="node",
        aliases=["js", "node", "nodejs"],
    ),
    "typescript": LanguageSpec(
        name="TypeScript",
        file_extension=".ts",
        interpreter="npx",
        aliases=["ts"],
    ),
    "ruby": LanguageSpec(
        name="Ruby",
        file_extension=".rb",
        interpreter="ruby",
        aliases=["rb"],
    ),
    "php": LanguageSpec(
        name="PHP",
        file_extension=".php",
        interpreter="php",
        aliases=[],
    ),
    "perl": LanguageSpec(
        name="Perl",
        file_extension=".pl",
        interpreter="perl",
        aliases=[],
    ),
    "lua": LanguageSpec(
        name="Lua",
        file_extension=".lua",
        interpreter="lua",
        aliases=[],
    ),
}

# Legacy Format für Kompatibilität
LANGUAGE_CONFIG: Dict[str, Dict[str, any]] = {
    "python": {"file": "code.py", "cmd": ["python", "/workspace/code.py"]},
    "bash": {"file": "code.sh", "cmd": ["bash", "/workspace/code.sh"]},
    "sh": {"file": "code.sh", "cmd": ["sh", "/workspace/code.sh"]},
    "javascript": {"file": "code.js", "cmd": ["node", "/workspace/code.js"]},
    "js": {"file": "code.js", "cmd": ["node", "/workspace/code.js"]},
    "node": {"file": "code.js", "cmd": ["node", "/workspace/code.js"]},
    "typescript": {"file": "code.ts", "cmd": ["npx", "ts-node", "/workspace/code.ts"]},
    "ts": {"file": "code.ts", "cmd": ["npx", "ts-node", "/workspace/code.ts"]},
    "ruby": {"file": "code.rb", "cmd": ["ruby", "/workspace/code.rb"]},
    "rb": {"file": "code.rb", "cmd": ["ruby", "/workspace/code.rb"]},
    "php": {"file": "code.php", "cmd": ["php", "/workspace/code.php"]},
    "perl": {"file": "code.pl", "cmd": ["perl", "/workspace/code.pl"]},
    "lua": {"file": "code.lua", "cmd": ["lua", "/workspace/code.lua"]},
}


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def _build_alias_map() -> Dict[str, str]:
    """Baut Alias → Sprache Mapping."""
    alias_map = {}
    for lang_name, spec in LANGUAGES.items():
        alias_map[lang_name] = lang_name
        for alias in spec.aliases:
            alias_map[alias] = lang_name
    return alias_map

_ALIAS_MAP = _build_alias_map()


def normalize_language(language: str) -> str:
    """
    Normalisiert Sprach-String zu kanonischem Namen.
    
    Args:
        language: Sprache oder Alias (z.B. "py", "js")
        
    Returns:
        Kanonischer Name (z.B. "python", "javascript")
    """
    if not language:
        return "python"
    
    lang = language.lower().strip()
    return _ALIAS_MAP.get(lang, "python")


def get_language_config(language: str) -> Dict[str, any]:
    """
    Gibt Dateiname und Command für eine Sprache zurück.
    
    Args:
        language: Sprache oder Alias
        
    Returns:
        Dict mit "file" und "cmd" Keys
    """
    lang = (language or "python").lower().strip()
    return LANGUAGE_CONFIG.get(lang, LANGUAGE_CONFIG["python"])


def get_language_spec(language: str) -> LanguageSpec:
    """
    Gibt LanguageSpec für eine Sprache zurück.
    
    Args:
        language: Sprache oder Alias
        
    Returns:
        LanguageSpec Instanz
    """
    normalized = normalize_language(language)
    return LANGUAGES.get(normalized, LANGUAGES["python"])


def is_language_supported(language: str) -> bool:
    """
    Prüft ob eine Sprache unterstützt wird.
    
    Args:
        language: Sprache oder Alias
        
    Returns:
        True wenn unterstützt
    """
    if not language:
        return True  # Default Python ist immer ok
    
    lang = language.lower().strip()
    return lang in LANGUAGE_CONFIG


def get_supported_languages() -> List[str]:
    """
    Gibt Liste aller unterstützten Sprachen zurück.
    
    Returns:
        Liste der Sprach-Namen
    """
    return list(LANGUAGES.keys())


def get_file_extension(language: str) -> str:
    """
    Gibt Datei-Extension für eine Sprache zurück.
    
    Args:
        language: Sprache oder Alias
        
    Returns:
        Extension mit Punkt (z.B. ".py")
    """
    spec = get_language_spec(language)
    return spec.file_extension
