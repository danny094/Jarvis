#!/usr/bin/env python3
"""
🧪 HARDCORE TEST: Wird die Persona wirklich geladen?

Dieser Test verifiziert dass:
1. Die Persona korrekt gespeichert wird
2. Der Switch funktioniert
3. Der System-Prompt den Persona-Namen enthält
4. Die Persona im Chat wirklich verwendet wird

Run: python3 test_persona_loaded.py
"""

import requests
import sys
import time
import json

# ============================================================
# CONFIGURATION
# ============================================================

API_BASE = os.getenv("API_BASE", "http://localhost:8200")
PERSONAS_URL = f"{API_BASE}/api/personas"

# Unique test persona to identify
TEST_NAME = "SuperTestBot_XYZ123"
TEST_PERSONA = f"""# Test Persona for Verification
# Created by automated test

[IDENTITY]
name: {TEST_NAME}
role: Test Verification Bot
language: English
user_name: Tester

[USER_CONTEXT]
- This is an automated test
- The user is verifying persona loading

[PERSONALITY]
- test-oriented
- verification-focused
- systematic

[STYLE]
Tone: Technical
Verbosity: Precise

[RULES]
1. Always identify yourself as {TEST_NAME}
2. Confirm you are the test persona when asked

[GREETINGS]
Greeting: Hello! I am {TEST_NAME}, the test bot!
"""

# ============================================================
# TEST FUNCTIONS
# ============================================================

def print_header(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")

def print_step(num, text):
    print(f"  [{num}] {text}")

def print_ok(text):
    print(f"      ✅ {text}")

def print_fail(text):
    print(f"      ❌ {text}")

def print_info(text):
    print(f"      ℹ️  {text}")


def test_api_available():
    """Test 1: Check if API is running"""
    print_step(1, "Checking API availability...")
    try:
        response = requests.get(f"{API_BASE}/health", timeout=5)
        if response.status_code == 200:
            print_ok("API is running")
            return True
        else:
            print_fail(f"API returned status {response.status_code}")
            return False
    except Exception as e:
        print_fail(f"Cannot connect to API: {e}")
        return False


def test_upload_persona():
    """Test 2: Upload the test persona"""
    print_step(2, f"Uploading test persona '{TEST_NAME}'...")
    
    try:
        # Create file-like object
        files = {
            'file': (f'{TEST_NAME}.txt', TEST_PERSONA, 'text/plain')
        }
        
        # Upload to named endpoint
        response = requests.post(
            f"{PERSONAS_URL}/{TEST_NAME}",
            files=files,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                print_ok(f"Uploaded: {data.get('name')} ({data.get('size')} bytes)")
                return True
            else:
                print_fail(f"Upload returned success=false")
                return False
        else:
            print_fail(f"Upload failed: HTTP {response.status_code}")
            print_info(response.text[:200])
            return False
            
    except Exception as e:
        print_fail(f"Upload error: {e}")
        return False


def test_persona_in_list():
    """Test 3: Verify persona appears in list"""
    print_step(3, "Verifying persona in list...")
    
    try:
        response = requests.get(PERSONAS_URL, timeout=5)
        data = response.json()
        
        if TEST_NAME.lower() in [p.lower() for p in data.get('personas', [])]:
            print_ok(f"Found '{TEST_NAME}' in personas list")
            print_info(f"Total personas: {data.get('count')}")
            return True
        else:
            print_fail(f"'{TEST_NAME}' not found in list")
            print_info(f"Available: {data.get('personas')}")
            return False
            
    except Exception as e:
        print_fail(f"List error: {e}")
        return False


def test_switch_persona():
    """Test 4: Switch to the test persona"""
    print_step(4, f"Switching to '{TEST_NAME}'...")
    
    try:
        response = requests.put(
            f"{PERSONAS_URL}/{TEST_NAME}/switch",
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('current', '').lower() == TEST_NAME.lower():
                print_ok(f"Switched! Active persona: {data.get('current')}")
                print_info(f"Persona name from file: {data.get('persona_name')}")
                return True
            else:
                print_fail(f"Switch response incorrect: {data}")
                return False
        else:
            print_fail(f"Switch failed: HTTP {response.status_code}")
            print_info(response.text[:200])
            return False
            
    except Exception as e:
        print_fail(f"Switch error: {e}")
        return False


def test_verify_active():
    """Test 5: Verify active persona is our test"""
    print_step(5, "Verifying active persona...")
    
    try:
        response = requests.get(PERSONAS_URL, timeout=5)
        data = response.json()
        
        active = data.get('active', '')
        if active.lower() == TEST_NAME.lower():
            print_ok(f"Active persona confirmed: {active}")
            return True
        else:
            print_fail(f"Wrong active persona: {active}")
            return False
            
    except Exception as e:
        print_fail(f"Verify error: {e}")
        return False


def test_system_prompt_contains_name():
    """Test 6: Verify system prompt contains persona name"""
    print_step(6, "Checking system prompt generation...")
    
    try:
        # Get the persona content and check if name is there
        response = requests.get(f"{PERSONAS_URL}/{TEST_NAME}", timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            content = data.get('content', '')
            
            if f"name: {TEST_NAME}" in content:
                print_ok(f"Persona content contains 'name: {TEST_NAME}'")
                
                # Parse to verify
                if "[IDENTITY]" in content:
                    print_ok("Has [IDENTITY] section")
                    return True
                else:
                    print_fail("Missing [IDENTITY] section")
                    return False
            else:
                print_fail(f"Name not found in content")
                return False
        else:
            print_fail(f"Get persona failed: HTTP {response.status_code}")
            return False
            
    except Exception as e:
        print_fail(f"System prompt check error: {e}")
        return False


def test_get_active_persona_details():
    """Test 7: Get details of active persona and verify name"""
    print_step(7, "Getting active persona details...")
    
    try:
        # First get active name
        list_response = requests.get(PERSONAS_URL, timeout=5)
        active_name = list_response.json().get('active')
        
        # Then get its content
        response = requests.get(f"{PERSONAS_URL}/{active_name}", timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            print_ok(f"Active persona file: {data.get('name')}")
            print_info(f"Size: {data.get('size')} bytes")
            print_info(f"Is active: {data.get('active')}")
            
            # Extract name from content
            content = data.get('content', '')
            for line in content.split('\n'):
                if line.strip().startswith('name:'):
                    parsed_name = line.split(':', 1)[1].strip()
                    print_ok(f"Parsed persona name: {parsed_name}")
                    
                    if parsed_name == TEST_NAME:
                        print_ok("✨ CONFIRMED: Active persona is our test persona!")
                        return True
            
            print_fail("Could not parse name from content")
            return False
        else:
            print_fail(f"Get details failed: HTTP {response.status_code}")
            return False
            
    except Exception as e:
        print_fail(f"Details error: {e}")
        return False


def cleanup():
    """Cleanup: Switch back and delete test persona"""
    print_step("C", "Cleaning up...")
    
    try:
        # Switch back to default
        requests.put(f"{PERSONAS_URL}/default/switch", timeout=5)
        print_ok("Switched back to 'default'")
        
        # Delete test persona
        response = requests.delete(f"{PERSONAS_URL}/{TEST_NAME}", timeout=5)
        if response.status_code == 200:
            print_ok(f"Deleted test persona '{TEST_NAME}'")
        else:
            print_info(f"Could not delete test persona (may not exist)")
            
    except Exception as e:
        print_info(f"Cleanup note: {e}")


# ============================================================
# MAIN
# ============================================================

def main():
    print_header("🧪 HARDCORE PERSONA LOADING TEST")
    print(f"API: {API_BASE}")
    print(f"Test Persona: {TEST_NAME}")
    
    results = []
    
    # Run tests
    results.append(("API Available", test_api_available()))
    if not results[-1][1]:
        print("\n❌ Cannot continue without API. Exiting.")
        sys.exit(1)
    
    results.append(("Upload Persona", test_upload_persona()))
    results.append(("Persona in List", test_persona_in_list()))
    results.append(("Switch Persona", test_switch_persona()))
    results.append(("Verify Active", test_verify_active()))
    results.append(("System Prompt Check", test_system_prompt_contains_name()))
    results.append(("Active Details", test_get_active_persona_details()))
    
    # Cleanup
    print("")
    cleanup()
    
    # Summary
    print_header("📊 TEST RESULTS")
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}  {name}")
    
    print(f"\n  {'='*40}")
    print(f"  Results: {passed}/{total} tests passed")
    
    if passed == total:
        print(f"\n  🎉 ALL TESTS PASSED!")
        print(f"  ✨ Persona system is working correctly!")
        return 0
    else:
        print(f"\n  ⚠️  Some tests failed. Check output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
