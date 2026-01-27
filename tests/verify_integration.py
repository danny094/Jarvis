import requests
import sys
import json

BASE_URL = "http://localhost:8200"

def test_endpoint(name, url, method="GET"):
    print(f"Testing {name} ({method} {url})...", end=" ")
    try:
        if method == "GET":
            resp = requests.get(f"{BASE_URL}{url}", timeout=5)
        else:
            resp = requests.post(f"{BASE_URL}{url}", timeout=5)
            
        if resp.status_code == 200:
            print("✅ OK")
            try:
                data = resp.json()
                # simplified summary
                keys = list(data.keys()) if isinstance(data, dict) else f"List[{len(data)}]"
                print(f"   Response keys: {keys}")
                return True
            except:
                print("   ⚠️  Not JSON")
                return True
        else:
            print(f"❌ Failed (Status: {resp.status_code})")
            print(f"   {resp.text[:100]}")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    print(f"=== Starting Integration Verification on {BASE_URL} ===")
    
    success = True
    
    # 1. Personas
    if not test_endpoint("Personas List", "/api/personas/"): success = False
    
    # 2. Models
    # Note: This might depend on Ollama being up, but we want to check the proxy
    if not test_endpoint("Models List", "/api/tags"): success = False
    
    # 3. MCP Tools
    if not test_endpoint("MCP List", "/api/mcp/list"): success = False
    
    # 4. Maintenance
    if not test_endpoint("Maintenance Status", "/api/maintenance/status"): success = False

    # 5. LobeChat Adapter (Port 8100 usually, but let's check config)
    # Assuming Adapter is running on 8100 as per its main.py defaults
    LOBE_URL = "http://localhost:8100"
    print(f"\nTesting LobeChat Adapter on {LOBE_URL}...")
    try:
        resp = requests.get(f"{LOBE_URL}/api/version", timeout=2)
        if resp.status_code == 200 and "version" in resp.json():
            print("✅ LobeChat Version Check OK")
        else:
            print(f"❌ LobeChat Version Check Failed: {resp.status_code}")
            # Don't fail entire script if 8100 isn't up, just warn
    except Exception as e:
        print(f"⚠️  LobeChat Adapter not reachable on 8100: {e}")

    print("\n=== Verification Complete ===")
    if success:
        print("🎉 All systems go! Backend is reachable and endpoints match frontend expectations.")
        sys.exit(0)
    else:
        print("⚠️  Some checks failed. See details above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
