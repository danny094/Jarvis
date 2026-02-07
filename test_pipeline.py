
import requests
import json
import time

SERVER_URL = "http://localhost:8088" # skill-server (outside docker)
EXECUTOR_URL = "http://localhost:8000" # tool-executor (exposed port)

def test_pipeline():
    print("=== Testing Tool Execution Pipeline ===")
    
    # 1. Test Tool Executor Health
    print("\n1. Checking Tool Executor Health...")
    try:
        resp = requests.get(f"{EXECUTOR_URL}/")
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.json()}")
    except Exception as e:
        print(f"FATAL: Tool Executor not reachable at {EXECUTOR_URL}: {e}")
        return

    # 2. Test Skill Server Health
    print("\n2. Checking Skill Server Health...")
    try:
        resp = requests.get(f"{SERVER_URL}/")
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.json()}")
    except Exception as e:
        print(f"FATAL: Skill Server not reachable at {SERVER_URL}: {e}")
        return

    # 3. Create a Skill (via Skill Server Proxy)
    print("\n3. Creating Skill 'test_pipeline_skill'...")
    skill_payload = {
        "name": "create_skill",
        "arguments": {
            "name": "test_pipeline_skill",
            "description": "A skill created to test the pipeline",
            "triggers": ["test", "pipeline"],
            "code": "def run(**kwargs):\n    return {'status': 'success', 'msg': 'Pipeline works!'}",
            "auto_promote": True 
        }
    }
    
    try:
        # We use the REST endpoint for tool calling
        resp = requests.post(f"{SERVER_URL}/tools/call", json=skill_payload)
        print(f"Status: {resp.status_code}")
        result = resp.json()
        print(f"Response: {json.dumps(result, indent=2)}")
        
        content = result.get("content", [{}])[0].get("text", "{}")
        data = json.loads(content)
        
        if data.get("success"):
            print("SUCCESS: Skill creation reported success.")
        else:
            print("FAILURE: Skill creation failed.")
            
    except Exception as e:
        print(f"Error calling create_skill: {e}")

    # 4. Verify Installation (List Skills)
    print("\n4. Verifying Installation...")
    try:
        resp = requests.post(f"{SERVER_URL}/tools/call", json={"name": "list_skills", "arguments": {}})
        result = resp.json()
        content = result.get("content", [{}])[0].get("text", "{}")
        data = json.loads(content)
        
        installed = [s["name"] for s in data.get("installed", [])]
        print(f"Installed Skills: {installed}")
        
        if "test_pipeline_skill" in installed:
            print("SUCCESS: Skill found in registry.")
        else:
            print("FAILURE: Skill not found in registry.")
            
    except Exception as e:
        print(f"Error listing skills: {e}")

if __name__ == "__main__":
    test_pipeline()
