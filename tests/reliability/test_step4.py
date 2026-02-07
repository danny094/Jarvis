"""
Test for correct_course() and apply_guardrails() (Step 4)
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
print("STEP 4: TESTING CORRECT_COURSE() & APPLY_GUARDRAILS()")
print("="*70)

# Initialize
safety = create_safety_layer()

# === TEST 1: CORRECT_COURSE() - POST HOC FALLACY ===
print("\nTEST 1: CORRECT_COURSE - Post Hoc Fallacy")
print("-" * 70)

step1 = MockStep(
    id="test1",
    query="Sales increased after ad campaign, therefore ads caused sales",
    context={"text": "Sales increased after ad campaign, therefore ads caused sales"}
)

print("Original query:")
print(f"  {step1.query}")

# Correct the derailed step
corrected_step1 = safety.correct_course(step1, verbose=False)

print(f"\nCorrected query:")
print(f"  {corrected_step1.query[:150]}...")

assert corrected_step1.query != step1.query, "Query should have been modified"
assert "therefore" not in corrected_step1.query, "Causal language should be removed"
print("✅ TEST 1 PASSED!")

# === TEST 2: CORRECT_COURSE() - CORRELATION-CAUSATION ===
print("\nTEST 2: CORRECT_COURSE - Correlation-Causation")
print("-" * 70)

step2 = MockStep(
    id="test2",
    query="X and Y are correlated, so X causes Y",
    context={"text": "Ice cream sales and drownings correlate, so ice cream causes drownings"}
)

print("Original query:")
print(f"  {step2.query}")

corrected_step2 = safety.correct_course(step2, verbose=False)

print(f"\nCorrected query:")
print(f"  {corrected_step2.query[:150]}...")

assert corrected_step2.query != step2.query, "Query should have been modified"
assert " so " not in corrected_step2.query, "Causal connector should be removed"
print("✅ TEST 2 PASSED!")

# === TEST 3: CORRECT_COURSE() - CLEAN STEP (NO CORRECTION) ===
print("\nTEST 3: CORRECT_COURSE - Clean Step (should not change)")
print("-" * 70)

step3 = MockStep(
    id="test3",
    query="We conducted a randomized controlled trial",
    context={"text": "We conducted a randomized controlled trial to test causation"}
)

original_query = step3.query
corrected_step3 = safety.correct_course(step3, verbose=False)

print(f"Query unchanged: {corrected_step3.query == original_query}")

assert corrected_step3.query == original_query, "Clean step should not be modified"
print("✅ TEST 3 PASSED!")

# === TEST 4: APPLY_GUARDRAILS() - POST HOC IN RESULT ===
print("\nTEST 4: APPLY_GUARDRAILS - Post Hoc in Result")
print("-" * 70)

result1 = MockResult(
    output="Sales increased after the ad campaign, therefore ads caused the increase",
    reasoning="Temporal analysis"
)

print("Original output:")
print(f"  {result1.output}")

corrected_result1 = safety.apply_guardrails(result1, verbose=False)

print(f"\nCorrected output:")
print(f"  {corrected_result1.output[:200]}...")

assert corrected_result1.output != result1.output, "Output should have been modified"
assert "IMPORTANT CAVEATS" in corrected_result1.output, "Should have caveats"
assert " therefore " not in corrected_result1.output, "Causal language should be weakened"
print("✅ TEST 4 PASSED!")

# === TEST 5: APPLY_GUARDRAILS() - CORRELATION-CAUSATION ===
print("\nTEST 5: APPLY_GUARDRAILS - Correlation-Causation")
print("-" * 70)

result2 = MockResult(
    output="X and Y are correlated, so X causes Y",
    reasoning="Correlation analysis"
)

print("Original output:")
print(f"  {result2.output}")

corrected_result2 = safety.apply_guardrails(result2, verbose=False)

print(f"\nCorrected output:")
print(f"  {corrected_result2.output[:200]}...")

assert corrected_result2.output != result2.output, "Output should have been modified"
assert "Correlation ≠ Causation" in corrected_result2.output, "Should mention correlation ≠ causation"
print("✅ TEST 5 PASSED!")

# === TEST 6: APPLY_GUARDRAILS() - CLEAN RESULT (NO CORRECTION) ===
print("\nTEST 6: APPLY_GUARDRAILS - Clean Result")
print("-" * 70)

result3 = MockResult(
    output="Rain is caused by water vapor condensing in clouds",
    reasoning="Scientific explanation"
)

original_output = result3.output
corrected_result3 = safety.apply_guardrails(result3, verbose=False)

print(f"Output unchanged: {corrected_result3.output == original_output}")

assert corrected_result3.output == original_output, "Clean result should not be modified"
print("✅ TEST 6 PASSED!")

# === TEST 7: VERBOSE MODE ===
print("\nTEST 7: VERBOSE MODE")
print("-" * 70)

step_verbose = MockStep(
    id="verbose",
    query="X happened before Y, so X caused Y",
    context={"text": "X happened before Y, so X caused Y"}
)

print("\nRunning correct_course with verbose=True:")
print("-" * 70)
corrected_verbose = safety.correct_course(step_verbose, verbose=True)

print("\n" + "=" * 70)
print("🎉 ALL TESTS PASSED!")
print("=" * 70)
print("\nFeatures Verified:")
print("  ✅ correct_course() - Fixes derailed steps")
print("  ✅ apply_guardrails() - Fixes biased results")
print("  ✅ Removes causal language")
print("  ✅ Adds correction notes/caveats")
print("  ✅ Preserves clean inputs")
print("  ✅ Verbose mode working")
print("\n✅ STEP 4 COMPLETE!")
print("="*70)
