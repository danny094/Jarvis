# tests/pipeline/test_control_sorting.py
import pytest
from .test_cases import CONTROL_SORTING_CASES

@pytest.mark.asyncio
async def test_control_sorting(analyze_query, extract_tools):
    """
    Validates the order of tool execution. 
    Note: ThinkingLayer outputs a LIST of suggested tools. 
    The ORDER in that list roughly corresponds to execution order by ControlLayer.
    """
    for case in CONTROL_SORTING_CASES:
        print(f"\nRunning Case: {case['id']} - {case['query']}")
        
        result = await analyze_query(case["query"])
        detected_tools = extract_tools(result)
        
        expected_order = case["expected_order"]
        
        # Filter detected tools to only include those in expected_order to avoid noise?
        # Or Strict check? Strict check better for logic verification.
        
        # Check if all expected tools are present
        missing = [t for t in expected_order if t not in detected_tools]
        assert not missing, f"MISS: Tools missing from plan: {missing}"
        
        # Check Order
        # Extract indices
        indices = [detected_tools.index(t) for t in expected_order]
        is_sorted = all(indices[i] <= indices[i+1] for i in range(len(indices)-1))
        
        assert is_sorted, \
            f"WRONG ORDER: [{case['id']}] Expected {expected_order}, got {detected_tools}"
