import sys
import os

# Adjust path to find core module if running from arbitrary location
sys.path.append("/DATA/AppData/MCP/Jarvis/Jarvis")

try:
    from core.tools.fast_lane.security import SecurePathValidator
except ImportError as e:
    print(f"FAILURE: Could not import SecurePathValidator. {e}")
    sys.exit(1)

print("Testing SecurePathValidator...")
validator = SecurePathValidator(safe_base="/DATA/AppData/MCP/Jarvis/Jarvis") # Use project dir as safe base for testing if trion-home likely missing

# Test 1: Blocked file
valid, path, err = validator.validate("/etc/passwd")
if not valid and "Path escapes safe directory" in err:
    print("SUCCESS: /etc/passwd blocked")
else:
    print(f"FAILURE: /etc/passwd not blocked properly. Result: {valid}, Err: {err}")
    sys.exit(1)

# Test 2: Valid file
valid, path, err = validator.validate("README.md")
if valid:
    print(f"SUCCESS: README.md allowed ({path})")
else:
    print(f"FAILURE: README.md not allowed properly. Result: {valid}, Err: {err}")
    sys.exit(1)
