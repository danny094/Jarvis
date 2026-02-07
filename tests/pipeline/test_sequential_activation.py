# tests/pipeline/test_sequential_activation.py
import pytest
from .test_cases import SEQUENTIAL_THINKING_CASES

@pytest.mark.asyncio
async def test_sequential_activation(analyze_query):
    """
    Validates if Sequential Thinking is activated for complex queries.
    """
    for case in SEQUENTIAL_THINKING_CASES:
        print(f"\nRunning Case: {case['id']} - {case['query']}")
        
        result = await analyze_query(case["query"])
        activated = result.get("needs_sequential_thinking", False)
        
        expected = case["needs_sequential"]
        
        if expected:
            assert activated, \
                f"MISS: [{case['id']}] Expected Sequential used, but was NOT. Complexity: {result.get('sequential_complexity')}"
        else:
            assert not activated, \
                f"FALSE POSITIVE: [{case['id']}] Expected NO Sequential, but was activated. Complexity: {result.get('sequential_complexity')}"
