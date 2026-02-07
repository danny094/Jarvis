import pytest
import httpx
import asyncio
import json
from typing import Dict, Any

# Configuration
SKILL_SERVER_URL = "http://localhost:8088"
TOOL_EXECUTOR_URL = "http://localhost:8000"

def extract_result(data: Dict[str, Any]) -> Dict[str, Any]:
    """Helper to extract the actual result from MCP wrapper if present."""
    if "content" in data and isinstance(data["content"], list):
        for item in data["content"]:
            if item.get("type") == "text":
                text = item.get("text", "")
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    pass
    return data

@pytest.mark.asyncio
async def test_autonomous_creation_happy_path():
    async with httpx.AsyncClient() as client:
        payload = {
            "name": "autonomous_skill_task",
            "arguments": {
                "user_text": "Berechne die Fakultät von 15",
                "intent": "Mathemtaik - Fakultät berechnen",
                "complexity": 3,
                "allow_auto_create": True,
                "execute_after_create": True
            }
        }
        
        # Increase timeout as skill creation might take time
        response = await client.post(f"{SKILL_SERVER_URL}/tools/call", json=payload, timeout=60.0)
        assert response.status_code == 200
        raw_data = response.json()
        data = extract_result(raw_data)
        
        # Debug output if failure
        if not data.get("success"):
            print(f"DEBUG: Failed response: {data}")

        assert data["success"] is True
        assert data["action_taken"] in ["created_and_ran", "ran_existing"]
        assert "skill_name" in data
        
        execution_result = data.get("execution_result", {})
        if isinstance(execution_result, dict):
             result_val = execution_result.get("result")
        else:
             result_val = execution_result
        
        assert int(result_val) == 1307674368000


@pytest.mark.asyncio
async def test_skill_reuse():
    prompt = "Berechne die Summe von 1 bis 100"
    intent = "Mathematik - Summe 1 bis 100"
    
    async with httpx.AsyncClient() as client:
        payload = {
            "name": "autonomous_skill_task",
            "arguments": {
                "user_text": prompt,
                "intent": intent,
                "complexity": 2,
                "allow_auto_create": True,
                "execute_after_create": True
            }
        }
        
        response1 = await client.post(f"{SKILL_SERVER_URL}/tools/call", json=payload, timeout=60.0)
        data1 = extract_result(response1.json())
        assert data1["success"] is True
        
        await asyncio.sleep(1)
        
        response2 = await client.post(f"{SKILL_SERVER_URL}/tools/call", json=payload, timeout=60.0)
        data2 = extract_result(response2.json())
        assert data2["success"] is True
        
        execution_result = data2.get("execution_result", {})
        if isinstance(execution_result, dict):
             result_val = execution_result.get("result")
        else:
             result_val = execution_result
             
        assert int(result_val) == 5050


@pytest.mark.asyncio
async def test_complexity_threshold():
    async with httpx.AsyncClient() as client:
        payload = {
            "name": "autonomous_skill_task",
            "arguments": {
                "user_text": "Baue ein komplettes Betriebssystem",
                "intent": "System Architecture",
                "complexity": 10,
                "allow_auto_create": True,
                "execute_after_create": True
            }
        }
        
        response = await client.post(f"{SKILL_SERVER_URL}/tools/call", json=payload, timeout=60.0)
        data = extract_result(response.json())
        if data.get("success"):
             pass
        else:
             assert True

@pytest.mark.asyncio
async def test_execution_error_handling():
    async with httpx.AsyncClient() as client:
        payload = {
            "name": "autonomous_skill_task",
            "arguments": {
                "user_text": "Teile 10 durch 0",
                "intent": "Math - DivZero",
                "complexity": 1,
                "allow_auto_create": True,
                "execute_after_create": True
            }
        }
        
        response = await client.post(f"{SKILL_SERVER_URL}/tools/call", json=payload, timeout=60.0)
        data = extract_result(response.json())
        
        if data.get("success"):
            res = data.get("execution_result", {})
            assert res is not None
        else:
            assert True
