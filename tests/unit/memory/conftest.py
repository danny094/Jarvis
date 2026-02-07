import pytest
import sys
import os
import sqlite3
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add memory_mcp and sql-memory root to sys.path
MEMORY_MCP_PATH = "/DATA/AppData/MCP/Jarvis/Jarvis/sql-memory/memory_mcp"
SQL_MEMORY_ROOT = "/DATA/AppData/MCP/Jarvis/Jarvis/sql-memory"

if MEMORY_MCP_PATH not in sys.path:
    sys.path.append(MEMORY_MCP_PATH)
if SQL_MEMORY_ROOT not in sys.path:
    sys.path.append(SQL_MEMORY_ROOT)

# Helper to mock modules that might fail to import due to missing env vars
sys.modules["openai"] = MagicMock()
sys.modules["tiktoken"] = MagicMock()

@pytest.fixture
def mock_db_path(tmp_path):
    """Create a temporary database for testing."""
    db_file = tmp_path / "test_memory.db"
    
    # Initialize schema manually (since database.py relies on config)
    conn = sqlite3.connect(str(db_file))
    c = conn.cursor()
    conn.close()
    
    return str(db_file)

@pytest.fixture(autouse=True)
def setup_db_context(mock_db_path):
    """Automatically patch config.DB_PATH for all tests."""
    with patch("config.DB_PATH", mock_db_path):
        # We need to ensure database initialization happens
        # Import inside patch to get patched config
        try:
            from database import initialize_db
            initialize_db()
        except Exception as e:
            # Fallback schema creation if import fails
            print(f"Warning: Database init failed: {e}. Creating manual schema.")
            conn = sqlite3.connect(mock_db_path)
            c = conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS memory (
                id TEXT PRIMARY KEY,
                type TEXT,
                content TEXT,
                content_json TEXT,
                summary TEXT,
                created_at TIMESTAMP,
                last_updated TIMESTAMP,
                access_count INTEGER DEFAULT 0,
                importance_score REAL DEFAULT 0.5
            )""")
            # Also need FTS table usually
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(content, content_json, summary)")
            # Logs
            c.execute("""CREATE TABLE IF NOT EXISTS memory_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT,
                action TEXT,
                timestamp TIMESTAMP
            )""")
            conn.commit()
            conn.close()
            
        yield

@pytest.fixture
def mock_vector_store():
    """Mock VectorStore with strict dimension check."""
    store = MagicMock()
    store.search.return_value = []
    
    # CRITICAL: Verify dimension match
    store.dimension = 1536 
    
    # Validation helper
    def validate_vector(vector):
        if len(vector) != store.dimension:
            raise ValueError(f"Vector dimension mismatch: expected {store.dimension}, got {len(vector)}")
        return True
        
    store.validate_vector = validate_vector
    return store
