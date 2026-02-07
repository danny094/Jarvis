# tests/pipeline/test_mcp_detection.py
import pytest
from .test_cases import MCP_DETECTION_CASES

@pytest.mark.asyncio
async def test_mcp_detection(analyze_query, extract_tools):
    """
    Validates if ThinkingLayer correctly selects tools based on query.
    """
    for case in MCP_DETECTION_CASES:
        print(f"\nRunning Case: {case['id']} - {case['query']}")
        
        result = await analyze_query(case["query"])
        detected = extract_tools(result)
        
        # Check Expected Tools
        for expected in case["expected_tools"]:
            assert expected in detected, \
                f"MISS: [{case['id']}] Expected '{expected}' but got {detected}. Intent: {result.get('intent')}"
        
        # Check NOT Expected (if defined in future)
        # ...
