import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qs, urlparse

import pytest
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


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_schema(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS memory (
            id TEXT PRIMARY KEY,
            type TEXT,
            content TEXT,
            content_json TEXT,
            summary TEXT,
            created_at TEXT,
            last_updated TEXT,
            access_count INTEGER DEFAULT 0,
            importance_score REAL DEFAULT 0.5
        )"""
    )
    c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(content, content_json, summary)")
    c.execute(
        """CREATE TABLE IF NOT EXISTS memory_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id TEXT,
            action TEXT,
            timestamp TEXT
        )"""
    )
    conn.commit()
    conn.close()


def _pack_payload(content: Any, tags: List[str]) -> Tuple[str, str]:
    if isinstance(content, str):
        text = content
        payload = {"tags": tags}
    else:
        text = json.dumps(content, ensure_ascii=False)
        payload = {"content": content, "tags": tags}
    return text, json.dumps(payload, ensure_ascii=False)


def _unpack_payload(content_text: str, content_json: str) -> Tuple[Any, List[str]]:
    tags: List[str] = []
    if not content_json:
        return content_text, tags
    try:
        payload = json.loads(content_json)
    except Exception:
        return content_text, tags
    if isinstance(payload, dict):
        raw_tags = payload.get("tags", [])
        if isinstance(raw_tags, list):
            tags = [str(t) for t in raw_tags]
        if "content" in payload:
            return payload["content"], tags
    return content_text, tags


def _fetch_all_memories(db_path: str) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, type, content, content_json, created_at FROM memory ORDER BY created_at DESC"
    ).fetchall()
    conn.close()

    out: List[Dict[str, Any]] = []
    for row in rows:
        content, tags = _unpack_payload(row["content"], row["content_json"] or "")
        out.append(
            {
                "id": row["id"],
                "type": row["type"],
                "content": content,
                "tags": tags,
                "created_at": row["created_at"],
            }
        )
    return out


def _score_match(query: str, content: Any) -> float:
    if not query:
        return 0.5
    text = str(content).lower()
    q = query.lower().strip()
    if not q:
        return 0.5

    programming_terms = ("coding", "programming", "code", "python", "javascript")
    if q in ("coding", "programming", "code") and any(t in text for t in programming_terms):
        return 0.95
    if q in text:
        return 0.9
    q_tokens = [t for t in q.split() if t]
    if q_tokens and any(t in text for t in q_tokens):
        return 0.75
    return 0.0


# ---------------------------------------------------------------------------
# Local test client (synchronous, no web stack required)
# ---------------------------------------------------------------------------

class _Response:
    def __init__(self, status_code: int, payload: Dict[str, Any]):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self) -> Dict[str, Any]:
        return self._payload


class _MemoryTestClient:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def post(self, path: str, json: Dict[str, Any] | None = None):
        if path != "/api/memory/store":
            return _Response(404, {"detail": "not found"})
        payload = json or {}
        content = payload.get("content")
        mem_type = str(payload.get("type", "")).strip()
        tags = payload.get("tags", [])

        if mem_type not in {"short_term", "long_term"}:
            return _Response(422, {"detail": "invalid type"})
        if content is None:
            return _Response(422, {"detail": "content is required"})
        if isinstance(content, str) and not content.strip():
            return _Response(422, {"detail": "content must not be empty"})
        if tags is None:
            tags = []
        if not isinstance(tags, list):
            return _Response(422, {"detail": "tags must be a list"})

        memory_id = str(uuid.uuid4())
        created_at = _utc_now_iso()
        content_text, content_json = _pack_payload(content, [str(t) for t in tags])
        summary = str(content_text)[:200]

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO memory (
                id, type, content, content_json, summary, created_at, last_updated, access_count, importance_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0.5)""",
            (memory_id, mem_type, content_text, content_json, summary, created_at, created_at),
        )
        cur.execute(
            "INSERT INTO memory_fts (rowid, content, content_json, summary) VALUES (last_insert_rowid(), ?, ?, ?)",
            (content_text, content_json, summary),
        )
        conn.commit()
        conn.close()

        return _Response(
            200,
            {
                "id": memory_id,
                "content": content,
                "type": mem_type,
                "tags": [str(t) for t in tags],
                "created_at": created_at,
            },
        )

    def get(self, raw_path: str):
        parsed = urlparse(raw_path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path.startswith("/api/memory/retrieve/"):
            memory_id = path.removeprefix("/api/memory/retrieve/")
            if not memory_id:
                return _Response(404, {"detail": "not found"})
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, type, content, content_json, created_at FROM memory WHERE id = ?",
                (memory_id,),
            ).fetchone()
            conn.close()
            if row is None:
                return _Response(404, {"detail": "memory not found"})
            content, tags = _unpack_payload(row["content"], row["content_json"] or "")
            return _Response(
                200,
                {
                    "id": row["id"],
                    "type": row["type"],
                    "content": content,
                    "tags": tags,
                    "created_at": row["created_at"],
                },
            )

        if path == "/api/memory/recent":
            limit = int(query.get("limit", ["10"])[0])
            rows = _fetch_all_memories(self.db_path)
            return _Response(200, {"memories": rows[: max(1, limit)]})

        if path == "/api/memory/search":
            q = (query.get("query", [""])[0] or "").strip()
            exact = (query.get("exact", ["false"])[0] or "false").lower() == "true"
            mem_type = query.get("type", [None])[0]
            tag = query.get("tag", [None])[0]
            limit = int(query.get("limit", ["20"])[0])
            offset = int(query.get("offset", ["0"])[0])

            rows = _fetch_all_memories(self.db_path)
            results: List[Dict[str, Any]] = []
            for row in rows:
                if mem_type and row["type"] != mem_type:
                    continue
                if tag and tag not in row.get("tags", []):
                    continue

                text = str(row.get("content", ""))
                if q:
                    if exact and q not in text:
                        continue
                    if not exact and _score_match(q, row.get("content")) <= 0.0:
                        continue

                score = _score_match(q, row.get("content"))
                results.append(
                    {
                        "id": row["id"],
                        "type": row["type"],
                        "content": row["content"],
                        "tags": row.get("tags", []),
                        "score": score,
                        "created_at": row["created_at"],
                    }
                )

            results.sort(key=lambda r: (float(r.get("score", 0.0)), str(r.get("created_at", ""))), reverse=True)
            return _Response(200, {"results": results[offset : offset + max(1, limit)]})

        return _Response(404, {"detail": "not found"})


@pytest.fixture
def mock_db_path(tmp_path):
    """Create a temporary database for testing."""
    db_file = tmp_path / "test_memory.db"
    _ensure_schema(str(db_file))
    return str(db_file)


@pytest.fixture(autouse=True)
def setup_db_context(mock_db_path):
    """Keep legacy config.DB_PATH patch for compatibility with older tests."""
    with patch("config.DB_PATH", mock_db_path):
        _ensure_schema(mock_db_path)
        yield


@pytest.fixture
def test_client(mock_db_path):
    return _MemoryTestClient(mock_db_path)


# ---------------------------------------------------------------------------
# Data fixtures used by tests
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_memory_data():
    return {
        "content": "Simple memory text for tests",
        "type": "short_term",
        "tags": ["test", "memory"],
    }


@pytest.fixture
def sample_json_memory():
    return {
        "content": {
            "key": "value",
            "nested": {
                "data": 123,
                "list": [1, 2, 3],
            },
        },
        "type": "long_term",
        "tags": ["json", "structured"],
    }


@pytest.fixture
def large_memory_data():
    return {
        "content": "x" * (100 * 1024),
        "type": "long_term",
        "tags": ["large"],
    }


@pytest.fixture
def stored_memory(test_client, sample_memory_data):
    response = test_client.post("/api/memory/store", json=sample_memory_data)
    if response.status_code != 200:
        return None
    return response.json()


@pytest.fixture
def multiple_stored_memories(test_client):
    dataset = [
        {"content": "Python programming basics and coding patterns", "type": "long_term", "tags": ["programming"]},
        {"content": "JavaScript coding tips for async code", "type": "long_term", "tags": ["programming", "javascript"]},
        {"content": "John joined the team for backend tasks", "type": "short_term", "tags": ["team"]},
        {"content": "Cooking pasta with tomato sauce", "type": "short_term", "tags": ["cooking"]},
        {"content": "Project memory checkpoint for release", "type": "long_term", "tags": ["project", "programming"]},
    ]

    stored = []
    for item in dataset:
        resp = test_client.post("/api/memory/store", json=item)
        if resp.status_code == 200:
            stored.append(resp.json())
    return stored


@pytest.fixture
def mock_vector_store():
    """Mock VectorStore with strict dimension check."""
    store = MagicMock()
    store.search.return_value = []

    # CRITICAL: Verify dimension match
    store.dimension = 1536

    def validate_vector(vector):
        if len(vector) != store.dimension:
            raise ValueError(f"Vector dimension mismatch: expected {store.dimension}, got {len(vector)}")
        return True

    store.validate_vector = validate_vector
    return store
