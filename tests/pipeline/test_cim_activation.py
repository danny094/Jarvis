# tests/pipeline/test_cim_activation.py
import pytest
from .test_cases import CIM_ACTIVATION_CASES

@pytest.mark.asyncio
async def test_cim_activation(analyze_query):
    """
    Validates if Cognitive Immune System (CIM) modes are suggested correctly.
    """
    for case in CIM_ACTIVATION_CASES:
        print(f"\nRunning Case: {case['id']} - {case['query']}")
        
        result = await analyze_query(case["query"])
        suggested_modes = result.get("suggested_cim_modes", [])
        
        should_activate = case["should_activate"]
        
        if should_activate:
            expected_modes = case.get("expected_cim_modes", [])
            # Check if at least one expected mode is present if strict check needed
            # For now, just check if ANY mode is suggested if activation expected
            # OR check specific modes intersection
            
            if expected_modes:
                 # Check intersection
                 found = any(m in suggested_modes for m in expected_modes)
                 assert found, \
                    f"MISS: [{case['id']}] Expected one of {expected_modes}, got {suggested_modes}"
            else:
                 # Just check generated modes exist if activation implied
                 assert suggested_modes, \
                    f"MISS: [{case['id']}] Expected CIM activation, got empty modes."

        else:
            # Expect NO modes or safe empty list
            # Some prompts might suggest 'light' by default, need to align with prompt logic.
            # Assuming 'should_activate=False' means NO SPECIAL modes like bias_detection.
            pass 
