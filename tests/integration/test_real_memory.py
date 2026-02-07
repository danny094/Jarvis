import os
import sys
# import pytest # Not needed for standalone execution
import sqlite3
import time

# Ensure current directory is in path (for imports inside container)
if os.getcwd() not in sys.path:
    sys.path.insert(0, os.getcwd())

from vector_store import VectorStore
from embedding import get_embedding

def test_real_connection_and_embedding():
    """
    Integration test:
    1. Connects to real SQLite DB (or creates new one).
    2. Generates real embedding via Ollama.
    3. Stores and retrieves memory.
    """
    print("\n[Integration] Starting Real Memory Test...")
    
    # 1. Check DB Path
    db_path = os.getenv("DB_PATH", "memory_integration_test.db")
    print(f"[Integration] Using DB: {db_path}")
    
    # 2. Check Embedding (Real Ollama Call)
    test_text = "The quick brown fox jumps over reference data."
    print(f"[Integration] Generating embedding for: '{test_text}'...")
    
    start_time = time.time()
    vec = get_embedding(test_text)
    duration = time.time() - start_time
    
    assert vec is not None, "Failed to get embedding from Ollama"
    assert len(vec) > 0, "Embedding vector is empty"
    print(f"[Integration] Embedding success! Size: {len(vec)}, Time: {duration:.2f}s")
    
    # 3. Store in VectorStore
    store = VectorStore(db_path)
    # Ensure clean state for test run?
    # No, let's append unique data
    unique_id = f"integ_test_{int(time.time())}"
    content = f"Integration Test Content {unique_id}"
    
    print(f"[Integration] Storing content: '{content}'...")
    entry_id = store.add(
        conversation_id="integration_test",
        content=content,
        content_type="test"
    )
    
    assert entry_id is not None, "Failed to store memory"
    print(f"[Integration] Stored with ID: {entry_id}")
    
    # 4. Search and Verify
    print("[Integration] Searching for content...")
    # Give DB a moment? SQLite is fast usually.
    results = store.search(
        query=f"Integration Test Content {unique_id}",
        conversation_id="integration_test",
        limit=1
    )
    
    assert len(results) > 0, "Search returned no results"
    match = results[0]
    print(f"[Integration] Found match: {match['content']} (Similarity: {match['similarity']:.4f})")
    
    assert match['content'] == content, "Retrieved content does not match"
    assert match['similarity'] > 0.9, "Similarity should be very high for exact match"
    
    print("[Integration] ✅ Test Complete - SUCCESS")

if __name__ == "__main__":
    # Allow running directly: python test_real_memory.py
    try:
        test_real_connection_and_embedding()
        sys.exit(0)
    except AssertionError as e:
        print(f"[Integration] ❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[Integration] ❌ ERROR: {e}")
        sys.exit(1)
