#!/usr/bin/env python3
"""
Test Light CIM Integration in ControlLayer
"""
import sys
import asyncio
sys.path.insert(0, "/DATA/AppData/MCP/Jarvis/Jarvis")

# Import ControlLayer
from core.layers.control import ControlLayer

print("✅ ControlLayer imported successfully!")

# Test instantiation
control = ControlLayer()
print(f"✅ ControlLayer instantiated")
print(f"   - Model: {control.model}")
print(f"   - Has light_cim: {hasattr(control, 'light_cim')}")
print(f"   - LightCIM type: {type(control.light_cim).__name__}")

# Test Light CIM directly
test_plan = {
    "intent": "Analyze sales data",
    "hallucination_risk": "low",
    "needs_memory": False,
    "memory_keys": []
}

result = control.light_cim.validate_basic(
    intent="Analyze sales data",
    hallucination_risk="low",
    user_text="Can you analyze my sales data?",
    thinking_plan=test_plan
)

print(f"\n✅ Light CIM validation works!")
print(f"   - Safe: {result['safe']}")
print(f"   - Confidence: {result['confidence']}")
print(f"   - Should escalate: {result['should_escalate']}")
print(f"   - Warnings: {result['warnings']}")

print("\n🎉 STEP 2 COMPLETE! ControlLayer + Light CIM working!")
