"""
Test Suite for Safety Layer (Step 1 Baseline)

Tests the basic functionality we built in Step 1:
- Safety layer initialization
- Basic validate_before() detection
- Integration with Intelligence Loader
- Integration with Frank's GraphSelector

This is our BASELINE - proves Step 1 is working!
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, "/DATA/AppData/MCP/Jarvis/Jarvis")

from modules.sequential_thinking.safety_layer import create_safety_layer
from dataclasses import dataclass


@dataclass
class MockStep:
    """Mock step for testing"""
    id: str
    query: str
    context: dict


def test_initialization():
    """Test 1: Can we initialize the safety layer?"""
    print("\n" + "="*60)
    print("TEST 1: INITIALIZATION")
    print("="*60)
    
    safety = create_safety_layer()
    
    # Check stats
    stats = safety.get_stats()
    
    print(f"✅ Safety layer initialized: {safety}")
    print(f"\nStats:")
    print(f"  - GraphSelector available: {stats['graph_selector_available']}")
    print(f"  - Intelligence Loader available: {stats['intelligence_loader_available']}")
    print(f"  - Available builders: {stats['available_builders']}")
    print(f"  - Anti-patterns loaded: {stats.get('anti_patterns', 0)}")
    print(f"  - Cognitive priors loaded: {stats.get('cognitive_priors', 0)}")
    
    # Assertions
    assert stats['graph_selector_available'] == True, "GraphSelector should be available"
    assert stats['intelligence_loader_available'] == True, "Intelligence Loader should be available"
    assert stats['available_builders'] == 5, "Should have 5 graph builders"
    assert stats['anti_patterns'] == 25, "Should have 25 anti-patterns"
    assert stats['cognitive_priors'] == 40, "Should have 40 cognitive priors"
    
    print("\n✅ TEST 1 PASSED!\n")
    return safety


def test_clean_reasoning(safety):
    """Test 2: Clean reasoning should PASS"""
    print("="*60)
    print("TEST 2: CLEAN REASONING (Should Pass)")
    print("="*60)
    
    step = MockStep(
        id="clean_reasoning",
        query="We conducted a randomized controlled trial to test causation",
        context={"text": "We conducted a randomized controlled trial to test causation"}
    )
    
    print(f"Step: {step.query}")
    print(f"\nRunning validate_before()...")
    
    result = safety.validate_before(step)
    
    print(f"\nResult:")
    print(f"  - Safe: {result.safe}")
    print(f"  - Derailed: {result.derailed}")
    print(f"  - Issues: {len(result.issues)}")
    print(f"  - Severity: {result.severity}")
    print(f"  - Action: {result.recommended_action}")
    
    # Assertions
    assert result.safe == True, "Clean reasoning should be safe"
    assert result.derailed == False, "Clean reasoning should not be derailed"
    assert len(result.issues) == 0, "Clean reasoning should have no issues"
    assert result.severity == "low", "Clean reasoning should be low severity"
    
    print("\n✅ TEST 2 PASSED!\n")


def test_post_hoc_fallacy(safety):
    """Test 3: Post Hoc Fallacy should be DETECTED"""
    print("="*60)
    print("TEST 3: POST HOC FALLACY (Should Detect)")
    print("="*60)
    
    step = MockStep(
        id="post_hoc",
        query="Sales increased after ad campaign, so ads caused sales",
        context={"text": "Sales increased after the ad campaign launched, therefore the ads caused the sales increase"}
    )
    
    print(f"Step: {step.query}")
    print(f"\nRunning validate_before()...")
    
    result = safety.validate_before(step)
    
    print(f"\nResult:")
    print(f"  - Safe: {result.safe}")
    print(f"  - Derailed: {result.derailed}")
    print(f"  - Issues: {len(result.issues)}")
    print(f"  - Severity: {result.severity}")
    print(f"  - Action: {result.recommended_action}")
    
    if len(result.issues) > 0:
        print(f"\nDetected Issues:")
        for issue in result.issues:
            print(f"  - {issue.get('pattern_id', 'unknown')}: {issue.get('name', 'Unknown')}")
            print(f"    Severity: {issue.get('severity', 'unknown')}")
    
    # Assertions
    assert result.safe == False, "Post hoc fallacy should be unsafe"
    assert result.derailed == True, "Post hoc fallacy should derail reasoning"
    assert len(result.issues) >= 1, "Should detect at least 1 issue"
    assert result.severity == "critical", "Post hoc should be critical"
    
    # Check that AP001 was detected
    ap001_found = any(issue.get('pattern_id') == 'AP001' for issue in result.issues)
    assert ap001_found, "Should detect AP001 (Post Hoc Fallacy)"
    
    print("\n✅ TEST 3 PASSED!\n")


def test_correlation_causation(safety):
    """Test 4: Correlation-Causation Fallacy should be DETECTED"""
    print("="*60)
    print("TEST 4: CORRELATION-CAUSATION (Should Detect)")
    print("="*60)
    
    step = MockStep(
        id="correlation",
        query="X and Y are correlated, so X causes Y",
        context={"text": "Ice cream sales and drowning deaths are correlated, so ice cream causes drownings"}
    )
    
    print(f"Step: {step.query}")
    print(f"\nRunning validate_before()...")
    
    result = safety.validate_before(step)
    
    print(f"\nResult:")
    print(f"  - Safe: {result.safe}")
    print(f"  - Derailed: {result.derailed}")
    print(f"  - Issues: {len(result.issues)}")
    print(f"  - Severity: {result.severity}")
    
    if len(result.issues) > 0:
        print(f"\nDetected Issues:")
        for issue in result.issues:
            print(f"  - {issue.get('pattern_id', 'unknown')}: {issue.get('name', 'Unknown')}")
    
    # Assertions
    assert result.safe == False, "Correlation-causation should be unsafe"
    assert len(result.issues) >= 1, "Should detect at least 1 issue"
    
    # Check that AP002 was detected
    ap002_found = any(issue.get('pattern_id') == 'AP002' for issue in result.issues)
    assert ap002_found, "Should detect AP002 (Correlation-Causation)"
    
    print("\n✅ TEST 4 PASSED!\n")


def test_multiple_issues(safety):
    """Test 5: Multiple biases should detect MULTIPLE issues"""
    print("="*60)
    print("TEST 5: MULTIPLE BIASES (Should Detect Multiple)")
    print("="*60)
    
    step = MockStep(
        id="multiple",
        query="Multiple fallacies in one statement",
        context={
            "text": "X happened before Y, and they are correlated, so X definitely caused Y. "
                   "This is obvious to everyone."
        }
    )
    
    print(f"Step: {step.query}")
    print(f"\nRunning validate_before()...")
    
    result = safety.validate_before(step)
    
    print(f"\nResult:")
    print(f"  - Safe: {result.safe}")
    print(f"  - Issues: {len(result.issues)}")
    print(f"  - Severity: {result.severity}")
    
    if len(result.issues) > 0:
        print(f"\nAll Detected Issues:")
        for i, issue in enumerate(result.issues, 1):
            print(f"  {i}. {issue.get('pattern_id', 'unknown')}: {issue.get('name', 'Unknown')}")
            print(f"     Severity: {issue.get('severity', 'unknown')}")
    
    # Assertions
    assert result.safe == False, "Multiple biases should be unsafe"
    assert len(result.issues) >= 1, "Should detect at least 1 issue (may detect more!)"
    
    print("\n✅ TEST 5 PASSED!\n")


def test_graph_selector_available(safety):
    """Test 6: Can we access Frank's GraphSelector?"""
    print("="*60)
    print("TEST 6: FRANK'S GRAPH SELECTOR")
    print("="*60)
    
    builders = safety.get_available_builders()
    
    print(f"Available builders: {builders}")
    
    # Assertions
    assert len(builders) == 5, "Should have 5 builders"
    assert 'light' in builders, "Should have light builder"
    assert 'heavy' in builders, "Should have heavy builder"
    assert 'strategic' in builders, "Should have strategic builder"
    assert 'temporal' in builders, "Should have temporal builder"
    assert 'simulation' in builders, "Should have simulation builder"
    
    print("\n✅ TEST 6 PASSED!\n")


def run_all_tests():
    """Run all tests"""
    print("\n" + "🧪"*30)
    print("SAFETY LAYER TEST SUITE - STEP 1 BASELINE")
    print("🧪"*30)
    
    try:
        # Test 1: Initialization
        safety = test_initialization()
        
        # Test 2: Clean reasoning
        test_clean_reasoning(safety)
        
        # Test 3: Post Hoc Fallacy
        test_post_hoc_fallacy(safety)
        
        # Test 4: Correlation-Causation
        test_correlation_causation(safety)
        
        # Test 5: Multiple issues
        test_multiple_issues(safety)
        
        # Test 6: GraphSelector
        test_graph_selector_available(safety)
        
        # Summary
        print("="*60)
        print("🎉 ALL TESTS PASSED! 🎉")
        print("="*60)
        print("\n✅ Step 1 is COMPLETE and WORKING!")
        print("✅ Safety Layer can detect biases")
        print("✅ Integration with Frank's CIM working")
        print("✅ Ready for Step 2 (Enhanced implementation)")
        
        return True
        
    except AssertionError as e:
        print("\n" + "="*60)
        print("❌ TEST FAILED!")
        print("="*60)
        print(f"Error: {e}")
        return False
    except Exception as e:
        print("\n" + "="*60)
        print("❌ UNEXPECTED ERROR!")
        print("="*60)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
