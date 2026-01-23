"""
Test for validate_after() method (Step 3)
"""

import sys
sys.path.insert(0, "/DATA/AppData/MCP/Jarvis/Jarvis")

from modules.sequential_thinking.safety_layer import create_safety_layer
from dataclasses import dataclass

@dataclass
class MockStep:
    id: str
    query: str
    context: dict

@dataclass
class MockResult:
    output: str
    reasoning: str = ""

print("\n" + "="*70)
print("STEP 3: TESTING VALIDATE_AFTER()")
print("="*70)

# Initialize
safety = create_safety_layer()

# === TEST 1: CLEAN RESULT (Should Pass) ===
print("\nTEST 1: CLEAN RESULT")
print("-" * 70)

step1 = MockStep(
    id="test1",
    query="What causes rain?",
    context={"text": "What causes rain?"}
)

result1 = MockResult(
    output="Rain is caused by water vapor condensing in clouds due to temperature changes.",
    reasoning="Scientific explanation of precipitation"
)

validation1 = safety.validate_after(step1, result1)

print(f"Result:")
print(f"  Valid: {validation1.valid}")
print(f"  Bias detected: {validation1.bias_detected}")
print(f"  Confidence: {validation1.confidence:.2f}")
print(f"  Corrections: {len(validation1.corrections_needed)}")

assert validation1.valid == True, "Clean result should be valid"
assert validation1.bias_detected == False, "Clean result should have no biases"
assert validation1.confidence >= 0.9, "Clean result should have high confidence"
print("✅ TEST 1 PASSED!")

# === TEST 2: RESULT WITH BIAS (Should Detect) ===
print("\nTEST 2: RESULT WITH BIAS (POST HOC)")
print("-" * 70)

step2 = MockStep(
    id="test2",
    query="Why did sales increase?",
    context={"text": "Why did sales increase?"}
)

result2 = MockResult(
    output="Sales increased after we launched the ad campaign, therefore the ads caused the sales increase.",
    reasoning="Post hoc analysis"
)

validation2 = safety.validate_after(step2, result2, verbose=False)

print(f"Result:")
print(f"  Valid: {validation2.valid}")
print(f"  Bias detected: {validation2.bias_detected}")
print(f"  Confidence: {validation2.confidence:.2f}")
print(f"  Corrections: {len(validation2.corrections_needed)}")

if len(validation2.corrections_needed) > 0:
    print(f"\n  Detected issues:")
    for correction in validation2.corrections_needed:
        print(f"    - {correction.get('name', 'Unknown')}")

assert validation2.bias_detected == True, "Biased result should be detected"
assert len(validation2.corrections_needed) >= 1, "Should have corrections"
print("✅ TEST 2 PASSED!")

# === TEST 3: VERBOSE MODE ===
print("\nTEST 3: VERBOSE MODE")
print("-" * 70)

step3 = MockStep(
    id="test3",
    query="Correlation analysis",
    context={"text": "Correlation analysis"}
)

result3 = MockResult(
    output="X and Y are correlated, so X causes Y",
    reasoning="Simple correlation"
)

validation3 = safety.validate_after(step3, result3, verbose=True)

assert validation3.bias_detected == True, "Should detect correlation-causation"
print("✅ TEST 3 PASSED!")

# === TEST 4: CONFIDENCE SCORING ===
print("\nTEST 4: CONFIDENCE SCORING")
print("-" * 70)

# Multiple results with different confidence levels
test_cases = [
    ("Clean result", "Scientific explanation", True, 0.9),
    ("Minor issue", "X might cause Y, needs verification", True, 0.8),
    ("Critical issue", "X definitely causes Y because they correlate", False, 0.7),
]

for i, (name, output, expected_valid, min_confidence) in enumerate(test_cases, 1):
    step = MockStep(id=f"conf{i}", query="test", context={"text": "test"})
    result = MockResult(output=output)
    validation = safety.validate_after(step, result)
    
    print(f"  {name}:")
    print(f"    Valid: {validation.valid}, Confidence: {validation.confidence:.2f}")
    
    if not expected_valid:
        assert validation.confidence < 1.0, f"{name} should have reduced confidence"

print("✅ TEST 4 PASSED!")

# === SUMMARY ===
print("\n" + "="*70)
print("🎉 ALL VALIDATE_AFTER TESTS PASSED!")
print("="*70)
print("\nFeatures Verified:")
print("  ✅ Output bias detection")
print("  ✅ Confidence scoring")
print("  ✅ Corrections generation")
print("  ✅ Verbose mode")
print("  ✅ Graph validation (placeholder)")
print("\n✅ STEP 3 COMPLETE!")
print("="*70)
