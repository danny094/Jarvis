# tests/run_all_tests.py
import pytest
import sys
import os
from datetime import datetime

DOCUMENTATION_DIR = "/app/documentation/Antigravity" if os.path.exists("/app") else "documentation/Antigravity"
REPORT_FILE = os.path.join(DOCUMENTATION_DIR, "TRION_TEST_REPORT.md")

def generate_report(exit_code):
    """
    Generates a generic report based on exit code.
    Ideally, this would parse pytest output (junitxml) for detailed stats.
    For now, we append a summary line.
    """
    status = "✅ PASSED" if exit_code == 0 else "❌ FAILED"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    report_content = f"""
# TRION Test Report ({timestamp})

**Status**: {status}

## Execution Summary
- **Pipeline Tests**: Executed via `pytest tests/pipeline`
- **Reliability Tests**: Executed via `pytest tests/reliability`

## Notes
See console output for detailed failure logs.
"""
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
    
    with open(REPORT_FILE, "w") as f:
        f.write(report_content)
    
    print(f"\nReport generated at: {REPORT_FILE}")

def main():
    print("🚀 Starting TRION Test Suite...")
    
    # Run Pipeline Tests
    print("\n--- Phase 1: Pipeline Tests (Decision Logic) ---")
    ret_pipeline = pytest.main(["-v", "tests/pipeline"])
    
    # Run Reliability Tests (Phase 2)
    print("\n--- Phase 2: Reliability Tests (Execution Stability) ---")
    ret_reliability = pytest.main(["-v", "tests/reliability"]) 
    
    total_exit = ret_pipeline + ret_reliability
    
    generate_report(total_exit)
    
    sys.exit(total_exit)

if __name__ == "__main__":
    main()
