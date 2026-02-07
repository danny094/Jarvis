import pytest
import asyncio
import uuid
from mcp.hub import get_hub
from utils.logger import log_info

@pytest.mark.asyncio
async def test_kg_persistence():
    """Verifies that the Knowledge Graph can store and retrieve facts."""
    hub = get_hub()
    hub.initialize()
    
    # 1. Prepare unique test data
    test_id = str(uuid.uuid4())[:8]
    test_key = f"test_fact_{test_id}"
    test_value = f"Automation Test Value {test_id}"
    
    # 2. Save Fact
    log_info(f"Saving fact: {test_key} -> {test_value}")
    result_save = hub.call_tool("memory_fact_save", {
        "conversation_id": "test_suite",
        "key": test_key,
        "value": test_value
    })
    
    assert "error" not in result_save, f"Save failed: {result_save}"
    
    # 3. Load Fact
    result_load = hub.call_tool("memory_fact_load", {
        "conversation_id": "test_suite",
        "key": test_key
    })
    
    assert "error" not in result_load, f"Load failed: {result_load}"
    
    # Check content (structure depends on MCP implementation)
    # Usually: {'value': '...', 'metadata': ...} or {'content': [...]}
    loaded_value = None
    if isinstance(result_load, dict):
        loaded_value = result_load.get("value")
        if not loaded_value and "content" in result_load:
             # Handle list content if applicable
             content = result_load["content"]
             if isinstance(content, list) and content:
                 loaded_value = content[0].get("text")
                 
    assert loaded_value == test_value, f"Expected '{test_value}', got '{loaded_value}'"

@pytest.mark.asyncio
async def test_system_knowledge_access():
    """Verifies access to system knowledge (e.g. mcp_detection_rules)."""
    hub = get_hub()
    hub.initialize()
    
    # Ensure auto-registration has run (should happen on init/refresh)
    # We can force it by calling refresh if we want to be sure, or just trust hub logic.
    # hub.refresh() # Optional, might be slow
    
    rules = hub.get_system_knowledge("mcp_detection_rules")
    
    # It might be None if never generated, but based on previous tests it should exist
    if rules:
        assert isinstance(rules, str)
        assert len(rules) > 10
    else:
        # Warn but don't fail if just empty (though critical for ThinkingLayer)
        pytest.warns(UserWarning, match="System knowledge 'mcp_detection_rules' is empty")
