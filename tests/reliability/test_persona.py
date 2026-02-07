#!/usr/bin/env python3
"""
Test Script für neue persona.py Funktionen
"""

import sys
sys.path.insert(0, '/DATA/AppData/MCP/Jarvis/Jarvis')

from core.persona import (
    list_personas,
    load_persona,
    save_persona,
    delete_persona,
    switch_persona,
    get_active_persona_name,
    get_persona
)

print("=" * 60)
print("PERSONA.PY FUNCTION TESTS")
print("=" * 60)

# Test 1: List personas
print("\n[TEST 1] list_personas()")
personas = list_personas()
print(f"✅ Found {len(personas)} personas: {personas}")

# Test 2: Load default
print("\n[TEST 2] load_persona('default')")
p = load_persona("default")
print(f"✅ Loaded: {p.name} - {p.role}")
print(f"   Language: {p.language}")
print(f"   Personality: {', '.join(p.personality[:3])}...")

# Test 3: Get active name
print("\n[TEST 3] get_active_persona_name()")
active = get_active_persona_name()
print(f"✅ Active: {active}")

# Test 4: Save test persona
print("\n[TEST 4] save_persona('test', content)")
test_content = """# Persona: Test
[IDENTITY]
name: Test Bot
role: Test Assistant

[PERSONALITY]
- testing
"""
result = save_persona("test", test_content)
print(f"✅ Save result: {result}")

# Test 5: List again (should include test)
print("\n[TEST 5] list_personas() - after save")
personas = list_personas()
print(f"✅ Personas now: {personas}")

# Test 6: Load test persona
print("\n[TEST 6] load_persona('test')")
p = load_persona("test")
print(f"✅ Loaded test: {p.name} - {p.role}")

# Test 7: Switch persona
print("\n[TEST 7] switch_persona('default')")
p = switch_persona("default")
active = get_active_persona_name()
print(f"✅ Switched to: {active}")

# Test 8: Delete test persona
print("\n[TEST 8] delete_persona('test')")
result = delete_persona("test")
print(f"✅ Delete result: {result}")

# Test 9: Try delete default (should fail)
print("\n[TEST 9] delete_persona('default') - SHOULD FAIL")
result = delete_persona("default")
print(f"✅ Protection works: {not result}")

# Test 10: Final list
print("\n[TEST 10] list_personas() - final")
personas = list_personas()
print(f"✅ Final personas: {personas}")

print("\n" + "=" * 60)
print("ALL TESTS COMPLETE!")
print("=" * 60)
