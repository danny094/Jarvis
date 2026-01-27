import requests
import zipfile
import io
import json
import time

BASE_URL = "http://localhost:8200"
OLLAMA_URL = "http://localhost:11434"

def step(name):
    print(f"\n======== {name} ========")

def test_health():
    step("Testing Health Endpoint")
    try:
        r = requests.get(f"{BASE_URL}/health")
        print(f"Status: {r.status_code}")
        print(f"Response: {r.json()}")
        assert r.status_code == 200
        print("✅ Health Check Passed")
    except Exception as e:
        print(f"❌ Health Check Failed: {e}")

def test_ollama():
    step("Testing Ollama Connection")
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags")
        print(f"Status: {r.status_code}")
        print("Models available:", [m['name'] for m in r.json().get('models', [])])
        assert r.status_code == 200
        print("✅ Ollama Check Passed")
    except Exception as e:
        print(f"❌ Ollama Connection Failed: {e}")

def create_mock_mcp_zip(name="test-mcp"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        config = {
            "name": name,
            "url": "http://example.com/mcp",
            "tier": "simple",
            "description": "Integration Test MCP",
            "enabled": True
        }
        z.writestr("config.json", json.dumps(config))
        z.writestr("requirements.txt", "# No deps")
        z.writestr("server.py", "# Dummy server")
    
    buffer.seek(0)
    return buffer

def test_installer():
    step("Testing MCP Installer")
    
    # 1. Create Zip
    zip_buffer = create_mock_mcp_zip("test-integration-mcp")
    
    # 2. Upload
    files = {'file': ('test.zip', zip_buffer, 'application/zip')}
    try:
        r = requests.post(f"{BASE_URL}/api/mcp/install", files=files)
        print(f"Upload Status: {r.status_code}")
        print(f"Response: {r.json()}")
        
        if r.status_code == 409:
            print("⚠️ MCP already exists (Acceptable for re-run)")
        else:
            assert r.status_code == 200
            print("✅ Install Successful")
            
    except Exception as e:
        print(f"❌ Install Failed: {e}")

def test_registry_list():
    step("Testing Registry List (Verify Hot Reload)")
    try:
        # Give it a moment for reload
        time.sleep(2)
        r = requests.get(f"{BASE_URL}/api/mcp/list")
        data = r.json()
        mcps = data.get("mcps", [])
        names = [m["name"] for m in mcps]
        print(f"Installed MCPs: {names}")
        
        if "test-integration-mcp" in names:
            print("✅ Custom MCP found in Registry!")
        else:
            print("❌ Custom MCP NOT found in Registry")
            
    except Exception as e:
        print(f"❌ Registry List Failed: {e}")

def test_chat_stream():
    step("Testing Chat Stream (End-to-End)")
    payload = {
        "model": "deepseek-r1:8b", # Or whatever is installed
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False
    }
    try:
        r = requests.post(f"{BASE_URL}/api/chat", json=payload)
        print(f"Chat Status: {r.status_code}")
        # Note: Might fail if model not pulled, so we just check connectivity
        if r.status_code == 200:
            print("✅ Chat Endpoint reachable")
        else:
            print(f"⚠️ Chat Warning: {r.text}")
            
    except Exception as e:
        print(f"❌ Chat Request Failed: {e}")

if __name__ == "__main__":
    print("🚀 Starting Backend Integration Tests...")
    test_health()
    test_ollama()
    test_installer()
    test_registry_list()
    # test_chat_stream() # Optional, depends on models
    print("\n🏁 Test Complete.")
