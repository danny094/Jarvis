# tests/test_persona.py
"""
Tests für das Persona-System.
"""

import pytest
from pathlib import Path


class TestPersonaLoading:
    """Tests für das Laden der Persona."""
    
    def test_load_persona(self):
        """Persona sollte geladen werden können."""
        from core.persona import load_persona
        
        persona = load_persona()
        
        assert persona is not None
        assert persona.name  # Sollte einen Namen haben
    
    def test_persona_has_required_fields(self):
        """Persona hat alle wichtigen Felder."""
        from core.persona import load_persona
        
        persona = load_persona()
        
        assert hasattr(persona, 'name')
        assert hasattr(persona, 'role')
        assert hasattr(persona, 'language')
        assert hasattr(persona, 'core_rules')
    
    def test_persona_builds_system_prompt(self):
        """System-Prompt kann generiert werden."""
        from core.persona import load_persona
        
        persona = load_persona()
        prompt = persona.build_system_prompt()
        
        assert isinstance(prompt, str)
        assert len(prompt) > 50  # Sollte substantiell sein
        assert persona.name in prompt
    
    def test_persona_config_exists(self):
        """Persona YAML existiert."""
        config_path = Path(__file__).parent.parent / "config" / "persona.yaml"
        
        assert config_path.exists(), "persona.yaml nicht gefunden"
    
    def test_get_persona_singleton(self):
        """get_persona gibt immer dieselbe Instanz."""
        from core.persona import get_persona
        
        p1 = get_persona()
        p2 = get_persona()
        
        assert p1 is p2  # Singleton


class TestPersonaContent:
    """Tests für den Inhalt der Persona."""
    
    def test_persona_is_jarvis(self):
        """Default Persona ist Jarvis."""
        from core.persona import load_persona
        
        persona = load_persona()
        
        assert persona.name == "Jarvis"
    
    def test_persona_speaks_german(self):
        """Persona spricht Deutsch."""
        from core.persona import load_persona
        
        persona = load_persona()
        
        assert persona.language.lower() == "deutsch"
    
    def test_persona_has_core_rules(self):
        """Persona hat Kern-Regeln."""
        from core.persona import load_persona
        
        persona = load_persona()
        
        assert len(persona.core_rules) > 0
        # Wichtige Regel sollte drin sein
        rules_text = " ".join(persona.core_rules).lower()
        assert "halluzin" in rules_text or "erfind" in rules_text
    
    def test_persona_knows_user(self):
        """Persona kennt den User-Namen."""
        from core.persona import load_persona
        
        persona = load_persona()
        
        assert persona.user_name  # Sollte gesetzt sein
