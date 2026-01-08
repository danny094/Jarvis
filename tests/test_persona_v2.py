# tests/test_persona_v2.py
"""
Tests für das Multi-Persona System (v2.0)
Erweitert das alte test_persona.py mit neuen Features.
"""

import pytest
import tempfile
import shutil
from pathlib import Path


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def temp_personas_dir(tmp_path):
    """Temporäres personas/ Verzeichnis für Tests."""
    personas_dir = tmp_path / "personas"
    personas_dir.mkdir()
    
    # Create default.txt
    default_content = """# Persona: Test Default
[IDENTITY]
name: Test Bot
role: Test Assistant
language: deutsch
user_name: TestUser

[PERSONALITY]
- friendly
- helpful

[STYLE]
tone: casual

[RULES]
1. Be helpful
2. Be honest

[PRIVACY]
- Protect user data

[GREETINGS]
greeting: Hello!
farewell: Bye!
"""
    (personas_dir / "default.txt").write_text(default_content, encoding="utf-8")
    
    return personas_dir


@pytest.fixture
def persona_module(temp_personas_dir, monkeypatch):
    """Persona Modul mit gemocktem PERSONAS_DIR."""
    from core import persona
    
    # Mock PERSONAS_DIR
    monkeypatch.setattr(persona, 'PERSONAS_DIR', temp_personas_dir)
    
    # Reset globals
    persona._persona_instance = None
    persona._active_persona_name = "default"
    
    return persona


# ============================================================
# BACKWARD COMPATIBILITY TESTS (alte Tests)
# ============================================================

class TestBackwardCompatibility:
    """Sicherstellen dass alte Funktionalität noch funktioniert."""
    
    def test_load_persona_works(self, persona_module):
        """load_persona() funktioniert wie vorher."""
        persona = persona_module.load_persona()
        
        assert persona is not None
        assert persona.name == "Test Bot"
    
    def test_get_persona_singleton(self, persona_module):
        """get_persona() gibt Singleton zurück."""
        p1 = persona_module.get_persona()
        p2 = persona_module.get_persona()
        
        assert p1 is p2
    
    def test_persona_has_required_fields(self, persona_module):
        """Persona hat alle wichtigen Felder."""
        persona = persona_module.load_persona()
        
        assert hasattr(persona, 'name')
        assert hasattr(persona, 'role')
        assert hasattr(persona, 'language')
        assert hasattr(persona, 'core_rules')
        assert hasattr(persona, 'personality')
    
    def test_build_system_prompt(self, persona_module):
        """build_system_prompt() generiert Text."""
        persona = persona_module.load_persona()
        prompt = persona.build_system_prompt()
        
        assert isinstance(prompt, str)
        assert len(prompt) > 50
        assert "Test Bot" in prompt


# ============================================================
# NEW MULTI-PERSONA TESTS
# ============================================================

class TestParsePersonaTxt:
    """Tests für parse_persona_txt()."""
    
    def test_parse_basic_txt(self, persona_module):
        """Einfaches .txt Format parsen."""
        content = """
[IDENTITY]
name: TestBot
role: Assistant
language: english

[PERSONALITY]
- friendly

[RULES]
1. Be nice
"""
        config = persona_module.parse_persona_txt(content)
        
        assert config['name'] == "TestBot"
        assert config['role'] == "Assistant"
        assert config['language'] == "english"
        assert "friendly" in config['personality']
        assert "Be nice" in config['core_rules']
    
    def test_parse_handles_comments(self, persona_module):
        """Kommentare werden ignoriert."""
        content = """
# This is a comment
[IDENTITY]
name: Bot
# Another comment
"""
        config = persona_module.parse_persona_txt(content)
        
        assert config['name'] == "Bot"
    
    def test_parse_handles_empty_sections(self, persona_module):
        """Leere Sections crashen nicht."""
        content = """
[IDENTITY]
name: Bot

[PERSONALITY]

[RULES]
"""
        config = persona_module.parse_persona_txt(content)
        
        assert config['name'] == "Bot"
        assert config['personality'] == []
        assert config['core_rules'] == []


class TestListPersonas:
    """Tests für list_personas()."""
    
    def test_list_finds_default(self, persona_module):
        """default.txt wird gefunden."""
        personas = persona_module.list_personas()
        
        assert "default" in personas
    
    def test_list_finds_multiple(self, persona_module, temp_personas_dir):
        """Mehrere Personas werden gefunden."""
        # Create additional personas
        (temp_personas_dir / "dev.txt").write_text("# Dev Persona", encoding="utf-8")
        (temp_personas_dir / "creative.txt").write_text("# Creative", encoding="utf-8")
        
        personas = persona_module.list_personas()
        
        assert len(personas) >= 3
        assert "default" in personas
        assert "dev" in personas
        assert "creative" in personas
    
    def test_list_sorted(self, persona_module, temp_personas_dir):
        """Liste ist sortiert."""
        (temp_personas_dir / "zebra.txt").write_text("# Z", encoding="utf-8")
        (temp_personas_dir / "alpha.txt").write_text("# A", encoding="utf-8")
        
        personas = persona_module.list_personas()
        
        # Should be alphabetically sorted
        assert personas == sorted(personas)


class TestLoadPersonaByName:
    """Tests für load_persona(name)."""
    
    def test_load_by_name(self, persona_module, temp_personas_dir):
        """Persona by name laden."""
        # Create test persona
        content = """
[IDENTITY]
name: DevBot
role: Developer
"""
        (temp_personas_dir / "dev.txt").write_text(content, encoding="utf-8")
        
        persona = persona_module.load_persona("dev")
        
        assert persona.name == "DevBot"
        assert persona.role == "Developer"
    
    def test_load_default_fallback(self, persona_module):
        """Bei fehlendem Namen wird default geladen."""
        persona = persona_module.load_persona("nonexistent")
        
        # Should fallback to default
        assert persona is not None
    
    def test_load_updates_cache(self, persona_module):
        """Laden updated die globale Instance."""
        p1 = persona_module.load_persona("default")
        p2 = persona_module.get_persona()
        
        assert p1 is p2


class TestSavePersona:
    """Tests für save_persona()."""
    
    def test_save_creates_file(self, persona_module, temp_personas_dir):
        """save_persona() erstellt Datei."""
        content = """
[IDENTITY]
name: New Persona
"""
        result = persona_module.save_persona("new", content)
        
        assert result is True
        assert (temp_personas_dir / "new.txt").exists()
    
    def test_save_sanitizes_filename(self, persona_module, temp_personas_dir):
        """Filename wird sanitized."""
        content = "[IDENTITY]\nname: Test"
        
        # Dangerous filename
        result = persona_module.save_persona("../../hack", content)
        
        assert result is True
        # Should be sanitized to safe name
        files = list(temp_personas_dir.glob("*.txt"))
        assert any("hack" in f.name for f in files)
        assert not any("../" in str(f) for f in files)
    
    def test_save_overwrites_existing(self, persona_module, temp_personas_dir):
        """Existing file wird überschrieben."""
        content1 = "[IDENTITY]\nname: First"
        content2 = "[IDENTITY]\nname: Second"
        
        persona_module.save_persona("test", content1)
        persona_module.save_persona("test", content2)
        
        # Load and verify
        saved = (temp_personas_dir / "test.txt").read_text()
        assert "Second" in saved


class TestDeletePersona:
    """Tests für delete_persona()."""
    
    def test_delete_removes_file(self, persona_module, temp_personas_dir):
        """delete_persona() löscht Datei."""
        # Create test file
        (temp_personas_dir / "deleteme.txt").write_text("test")
        
        result = persona_module.delete_persona("deleteme")
        
        assert result is True
        assert not (temp_personas_dir / "deleteme.txt").exists()
    
    def test_delete_protects_default(self, persona_module):
        """default kann nicht gelöscht werden."""
        result = persona_module.delete_persona("default")
        
        assert result is False
    
    def test_delete_nonexistent_returns_false(self, persona_module):
        """Löschen von nicht-existierender Persona gibt False."""
        result = persona_module.delete_persona("doesnotexist")
        
        assert result is False


class TestSwitchPersona:
    """Tests für switch_persona()."""
    
    def test_switch_updates_active(self, persona_module, temp_personas_dir):
        """switch_persona() updated active_name."""
        # Create second persona
        content = "[IDENTITY]\nname: DevBot"
        (temp_personas_dir / "dev.txt").write_text(content, encoding="utf-8")
        
        persona_module.switch_persona("dev")
        active = persona_module.get_active_persona_name()
        
        assert active == "dev"
    
    def test_switch_clears_cache(self, persona_module, temp_personas_dir):
        """switch_persona() clears cache."""
        # Load default
        p1 = persona_module.load_persona("default")
        
        # Create and switch
        content = "[IDENTITY]\nname: DevBot"
        (temp_personas_dir / "dev.txt").write_text(content, encoding="utf-8")
        
        p2 = persona_module.switch_persona("dev")
        
        assert p1 is not p2
        assert p2.name == "DevBot"
    
    def test_switch_returns_persona(self, persona_module):
        """switch_persona() gibt Persona zurück."""
        persona = persona_module.switch_persona("default")
        
        assert persona is not None
        assert hasattr(persona, 'name')


class TestGetActivePersonaName:
    """Tests für get_active_persona_name()."""
    
    def test_get_active_returns_default_initially(self, persona_module):
        """Initialer active name ist 'default'."""
        active = persona_module.get_active_persona_name()
        
        assert active == "default"
    
    def test_get_active_after_switch(self, persona_module, temp_personas_dir):
        """Nach switch gibt korrekten Namen zurück."""
        content = "[IDENTITY]\nname: Test"
        (temp_personas_dir / "test.txt").write_text(content, encoding="utf-8")
        
        persona_module.switch_persona("test")
        active = persona_module.get_active_persona_name()
        
        assert active == "test"


# ============================================================
# INTEGRATION TESTS
# ============================================================

class TestIntegration:
    """End-to-End Tests für das gesamte System."""
    
    def test_full_workflow(self, persona_module, temp_personas_dir):
        """Complete workflow: create, list, load, switch, delete."""
        # 1. List initial
        personas = persona_module.list_personas()
        assert len(personas) == 1  # only default
        
        # 2. Create new persona
        content = """
[IDENTITY]
name: WorkflowTest
role: Tester
"""
        persona_module.save_persona("workflow", content)
        
        # 3. List again
        personas = persona_module.list_personas()
        assert len(personas) == 2
        assert "workflow" in personas
        
        # 4. Load by name
        persona = persona_module.load_persona("workflow")
        assert persona.name == "WorkflowTest"
        
        # 5. Switch to it
        persona_module.switch_persona("workflow")
        assert persona_module.get_active_persona_name() == "workflow"
        
        # 6. Delete it
        result = persona_module.delete_persona("workflow")
        assert result is True
        
        # 7. List final
        personas = persona_module.list_personas()
        assert len(personas) == 1
    
    def test_multiple_personas_coexist(self, persona_module, temp_personas_dir):
        """Mehrere Personas können gleichzeitig existieren."""
        # Create 3 personas
        for name in ["dev", "creative", "security"]:
            content = f"[IDENTITY]\nname: {name.title()}"
            persona_module.save_persona(name, content)
        
        personas = persona_module.list_personas()
        assert len(personas) >= 4  # default + 3
        
        # Switch between them
        for name in ["dev", "creative", "security"]:
            p = persona_module.switch_persona(name)
            assert p.name == name.title()
            assert persona_module.get_active_persona_name() == name


# ============================================================
# ERROR HANDLING TESTS
# ============================================================

class TestErrorHandling:
    """Tests für Error-Handling."""
    
    def test_load_with_corrupted_txt(self, persona_module, temp_personas_dir):
        """Corrupted .txt führt zu graceful fallback."""
        # Create corrupted file
        (temp_personas_dir / "broken.txt").write_text("NOT VALID FORMAT!!!")
        
        # Should not crash, should fallback
        persona = persona_module.load_persona("broken")
        assert persona is not None
    
    def test_parse_with_invalid_sections(self, persona_module):
        """Invalid sections werden ignoriert."""
        content = """
[UNKNOWN_SECTION]
something: value

[IDENTITY]
name: Valid
"""
        config = persona_module.parse_persona_txt(content)
        
        assert config['name'] == "Valid"
    
    def test_save_with_permission_error(self, persona_module, temp_personas_dir, monkeypatch):
        """Permission error wird handled."""
        # Make directory read-only
        temp_personas_dir.chmod(0o444)
        
        result = persona_module.save_persona("test", "content")
        
        # Should return False, not crash
        assert result is False
        
        # Cleanup
        temp_personas_dir.chmod(0o755)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
