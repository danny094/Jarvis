from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
import os
import sqlite3
import json
from pathlib import Path
from datetime import datetime

# Import security validator
try:
    from core.tools.fast_lane.security import SecurePathValidator
except ImportError:
    from .security import SecurePathValidator


class BaseNativeTool(BaseModel):
    """Base class for Native Fast Lane Tools."""
    pass


# ==============================================================================
# HOME TOOLS (File Operations)
# ==============================================================================

class HomeReadTool(BaseNativeTool):
    """Reads a file from the TRION home directory."""
    path: str = Field(..., description="Path to the file to read, relative to TRION home.")
    
    def execute(self) -> str:
        validator = SecurePathValidator()
        is_valid, resolved, error = validator.validate(self.path)
        if not is_valid:
            raise ValueError(error)
            
        with open(resolved, 'r', encoding='utf-8') as f:
            return f.read()


class HomeWriteTool(BaseNativeTool):
    """Writes content to a file in the TRION home directory."""
    path: str = Field(..., description="Path to the file to write, relative to TRION home.")
    content: str = Field(..., description="Content to write to the file.")
    overwrite: bool = Field(False, description="Whether to overwrite existing files.")
    
    def execute(self) -> str:
        validator = SecurePathValidator()
        is_valid, resolved, error = validator.validate(self.path)
        if not is_valid:
            raise ValueError(error)
            
        if os.path.exists(resolved) and not self.overwrite:
            raise FileExistsError(f"File {self.path} already exists and overwrite is False.")
            
        # Ensure parent directory exists
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        
        with open(resolved, 'w', encoding='utf-8') as f:
            f.write(self.content)
            
        return f"File written successfully to {self.path}"


class HomeListTool(BaseNativeTool):
    """Lists files in a directory in the TRION home directory."""
    path: str = Field(".", description="Directory to list, relative to TRION home.")
    recursive: bool = Field(False, description="List recursively if True.")
    
    def execute(self) -> List[str]:
        validator = SecurePathValidator()
        is_valid, resolved, error = validator.validate(self.path)
        if not is_valid:
             raise ValueError(error)
             
        if not os.path.isdir(resolved):
            raise NotADirectoryError(f"Path {self.path} is not a directory.")
            
        results = []
        base_path = Path(resolved)
        
        if self.recursive:
            for root, dirs, files in os.walk(resolved):
                root_path = Path(root)
                for d in dirs:
                     results.append(str((root_path / d).relative_to(base_path)) + "/")
                for f in files:
                     results.append(str((root_path / f).relative_to(base_path)))
        else:
            for item in base_path.iterdir():
                 if item.is_dir():
                      results.append(item.name + "/")
                 else:
                      results.append(item.name)
                
        return sorted(results)


# ==============================================================================
# MEMORY & WORKSPACE TOOLS (Database Operations)
# ==============================================================================

def get_db_connection():
    """
    Get SQLite connection to memory.db with WAL mode
    
    Path: /app/memory_data/memory.db (mounted volume)
    """
    conn = sqlite3.connect(
        '/app/memory_data/memory.db',
        timeout=5.0,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    return conn


class MemorySaveTool(BaseNativeTool):
    """Saves memory text to database (embeddings computed async)."""
    content: str = Field(..., description="Content to save to memory")
    role: str = Field("user", description="Role: user or assistant")
    conversation_id: str = Field("unknown", description="Conversation ID")
    
    def execute(self) -> str:
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO memory (conversation_id, role, content, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (self.conversation_id, self.role, self.content, datetime.utcnow().isoformat())
                )
                conn.commit()
                row_id = cursor.lastrowid
                
            return f"Memory saved (ID: {row_id})"
            
        except Exception as e:
            raise RuntimeError(f"Failed to save memory: {str(e)}")


class MemorySearchTool(BaseNativeTool):
    """Search memory using Full-Text Search."""
    query: str = Field(..., description="Search query")
    limit: int = Field(5, description="Max results")
    conversation_id: Optional[str] = Field(None, description="Filter by conversation")
    
    def execute(self) -> List[str]:
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Simple LIKE search (FTS setup is optional)
                if self.conversation_id:
                    cursor.execute(
                        """
                        SELECT content, role, created_at
                        FROM memory
                        WHERE content LIKE ? AND conversation_id = ?
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (f"%{self.query}%", self.conversation_id, self.limit)
                    )
                else:
                    cursor.execute(
                        """
                        SELECT content, role, created_at
                        FROM memory
                        WHERE content LIKE ?
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (f"%{self.query}%", self.limit)
                    )
                
                results = cursor.fetchall()
                
            if not results:
                return []
            
            return [
                f"[{row['role']}] {row['content'][:200]}..." if len(row['content']) > 200 
                else f"[{row['role']}] {row['content']}"
                for row in results
            ]
            
        except Exception as e:
            raise RuntimeError(f"Failed to search memory: {str(e)}")


class WorkspaceEventSaveTool(BaseNativeTool):
    """Saves an internal workspace event to workspace_events (telemetry, read-only store)."""
    conversation_id: str = Field("unknown", description="Conversation ID")
    event_type: str = Field("observation", description="Event type")
    event_data: Optional[dict] = Field(None, description="Event payload")

    def execute(self) -> str:
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workspace_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        conversation_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        event_data TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )

                cursor.execute(
                    """
                    INSERT INTO workspace_events (conversation_id, event_type, event_data, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        self.conversation_id,
                        self.event_type,
                        json.dumps(self.event_data or {}),
                        datetime.utcnow().isoformat(),
                    ),
                )
                conn.commit()
                event_id = cursor.lastrowid

            return json.dumps({"id": event_id, "status": "saved"})

        except Exception as e:
            raise RuntimeError(f"Failed to save workspace event: {str(e)}")


class WorkspaceEventListTool(BaseNativeTool):
    """Lists workspace events from workspace_events (last 48 hours, read-only telemetry)."""
    conversation_id: Optional[str] = Field(None, description="Filter by conversation")
    event_type: Optional[str] = Field(None, description="Filter by event type")
    limit: int = Field(10, description="Max events")

    def execute(self) -> List[dict]:
        try:
            with get_db_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                query = """
                    SELECT id, conversation_id, event_type, event_data, created_at
                    FROM workspace_events
                    WHERE created_at >= datetime('now', '-2 days')
                """
                params: list = []

                if self.conversation_id:
                    query += " AND conversation_id = ?"
                    params.append(self.conversation_id)

                if self.event_type:
                    query += " AND event_type = ?"
                    params.append(self.event_type)

                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(self.limit)

                cursor.execute(query, params)
                results = cursor.fetchall()

            return [
                {
                    "id": row["id"],
                    "conversation_id": row["conversation_id"],
                    "event_type": row["event_type"],
                    "event_data": json.loads(row["event_data"]),
                    "created_at": row["created_at"],
                }
                for row in results
            ]

        except Exception as e:
            raise RuntimeError(f"Failed to list workspace events: {str(e)}")


# ==============================================================================
# TOOL REGISTRY
# ==============================================================================

NATIVE_TOOLS = {
    "home_read": HomeReadTool,
    "home_write": HomeWriteTool,
    "home_list": HomeListTool,
    "memory_save": MemorySaveTool,
    "memory_search": MemorySearchTool,
    "workspace_event_save": WorkspaceEventSaveTool,
    "workspace_event_list": WorkspaceEventListTool,
}


def get_native_tool_class(name: str):
    return NATIVE_TOOLS.get(name)


def get_fast_lane_tools_summary() -> List[Dict[str, Any]]:
    """Returns tool definitions for MCP Registry with proper inputSchema."""
    return [
        {
            "name": "home_read",
            "mcp": "fast-lane",
            "description": "Reads a file from the TRION home directory. FAST execution.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file, relative to TRION home."},
                },
                "required": ["path"],
            },
        },
        {
            "name": "home_write",
            "mcp": "fast-lane",
            "description": "Writes content to a file in the TRION home directory. FAST execution.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file, relative to TRION home."},
                    "content": {"type": "string", "description": "Content to write to the file."},
                    "overwrite": {"type": "boolean", "description": "Whether to overwrite existing files.", "default": False},
                },
                "required": ["path", "content"],
            },
        },
        {
            "name": "home_list",
            "mcp": "fast-lane",
            "description": "Lists contents of a directory in the TRION home. FAST execution.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path, relative to TRION home."},
                    "recursive": {"type": "boolean", "description": "Whether to list recursively.", "default": False},
                },
                "required": ["path"],
            },
        },
        {
            "name": "memory_save",
            "mcp": "fast-lane",
            "description": "Save memory to database (text-only). FAST execution.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Text content to save."},
                    "role": {"type": "string", "description": "Role (user/assistant)."},
                    "conversation_id": {"type": "string", "description": "Conversation ID."},
                },
                "required": ["content"],
            },
        },
        {
            "name": "memory_search",
            "mcp": "fast-lane",
            "description": "Search memory using keyword search. FAST execution.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "limit": {"type": "integer", "description": "Max results.", "default": 10},
                    "conversation_id": {"type": "string", "description": "Filter by conversation ID."},
                },
                "required": ["query"],
            },
        },
        {
            "name": "workspace_event_save",
            "mcp": "fast-lane",
            "description": "Save an internal workspace event (telemetry). FAST execution. Read-only store — not for user-editable notes.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "event_type": {"type": "string", "description": "Type of event (e.g. container_started, observation)."},
                    "event_data": {"type": "object", "description": "Event payload dict."},
                    "conversation_id": {"type": "string", "description": "Conversation ID."},
                },
                "required": ["event_type"],
            },
        },
        {
            "name": "workspace_event_list",
            "mcp": "fast-lane",
            "description": "List workspace events from the event store (last 48h). FAST execution. Read-only telemetry.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "conversation_id": {"type": "string", "description": "Filter by conversation ID."},
                    "event_type": {"type": "string", "description": "Filter by event type."},
                    "limit": {"type": "integer", "description": "Max results.", "default": 20},
                },
                "required": [],
            },
        },
    ]
