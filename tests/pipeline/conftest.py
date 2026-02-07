# tests/pipeline/conftest.py
import pytest
import asyncio
from typing import Dict, Any, List

# Create event loop for async tests
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
def thinking_layer():
    """
    Initializes the ThinkingLayer.
    Assumes standard config/environment is available (e.g. inside Docker container).
    """
    from core.layers.thinking import ThinkingLayer
    layer = ThinkingLayer()
    return layer

@pytest.fixture(scope="session")
def hub():
    """
    Initializes the MCPHub singleton.
    """
    from mcp.hub import get_hub
    return get_hub()

@pytest.fixture
def analyze_query(thinking_layer):
    """
    Fixture that returns an async function to analyze a query.
    Usage:
        result = await analyze_query("What time is it?")
    """
    async def _analyze(query: str) -> Dict[str, Any]:
        # non-streaming analysis for tests
        return await thinking_layer.analyze(query, memory_context="")
    return _analyze

@pytest.fixture
def extract_tools():
    """
    Helper to extract tool names from the plan.
    Logic may vary depending on how ThinkingLayer outputs 'tools'.
    Current Assumption: plan keys or specific 'suggested_tools' list?
    Actually ThinkingLayer outputs a 'plan' dict.
    But Layer 2 converts it to specific tool calls.
    
    If ThinkingLayer only outputs INTENT, we might need to rely on
    implied tool mapping logic or update ThinkingLayer output to be more explicit.
    
    For now, we check the mapped intent logic or if new field exists.
    However, Looking at ThinkingLayer prompts, it doesn't output 'tools' list explicitly in JSON.
    It outputs 'intent', 'needs_memory', etc.
    
    Wait! The 'tools' are determined in Layer 2 (Control) or implied by 'is_fact_query' + 'needs_memory'.
    
    Let's refine this fixture to interpret the Plan -> Tools mapping 
    similar to how ControlLayer would (or we mock ControlLayer).
    """
    def _extract(plan: Dict[str, Any]) -> List[str]:
        # 1. Direct Tools from Thinking
        tools = plan.get("suggested_tools", [])
        
        # 2. Implied Tools (optional fallback logic)
        if plan.get("needs_memory", False) and not any(t.startswith("memory_") for t in tools):
             if plan.get("is_fact_query", False):
                 tools.append("memory_graph_search")
             else:
                 tools.append("memory_save")
        
        return tools

        
    return _extract
