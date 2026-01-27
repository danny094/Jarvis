
import os
import sys

# Mock env vars if needed - mimicking config.py defaults
os.environ["CHARS_PER_TOKEN"] = "3.5"
os.environ["CHUNKING_THRESHOLD"] = "6000"

from utils.chunker import needs_chunking, estimate_tokens_fast, count_tokens

def test_chunking_logic():
    # Simulate the user's document
    # 27.7 KB ~ 27700 chars
    dummy_text = "a" * 27700
    
    print(f"Text length: {len(dummy_text)} chars")
    
    est = estimate_tokens_fast(dummy_text)
    print(f"Estimated tokens (fast): {est}")
    
    threshold = 6000
    needed = needs_chunking(dummy_text, threshold)
    print(f"Needs chunking (threshold={threshold})? {needed}")
    
    match = count_tokens(dummy_text, use_tiktoken=True)
    print(f"Count tokens (tiktoken/approx): {match}")

    if needed:
        print("SUCCESS: Logic works as expected.")
    else:
        print("FAILURE: Logic did NOT trigger chunking.")

if __name__ == "__main__":
    test_chunking_logic()
