"""
MCP Tool Definitions for Document Processor
"""

TOOLS = [
    {
        "name": "preprocess",
        "description": "Clean and preprocess text (normalize whitespace, add paragraph IDs, remove artifacts)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to preprocess"},
                "add_paragraph_ids": {"type": "boolean", "description": "Add paragraph IDs", "default": True},
                "normalize_whitespace": {"type": "boolean", "description": "Normalize whitespace", "default": True},
                "remove_artifacts": {"type": "boolean", "description": "Remove markdown artifacts", "default": True}
            },
            "required": ["text"]
        }
    },
    {
        "name": "analyze_structure",
        "description": "Analyze document structure WITHOUT LLM (headings, code blocks, keywords, complexity)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to analyze"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "build_index",
        "description": "Build searchable index for document",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to index"},
                "conversation_id": {"type": "string", "description": "Session ID"},
                "generate_summaries": {"type": "boolean", "description": "Generate section summaries", "default": False}
            },
            "required": ["text", "conversation_id"]
        }
    },
    {
        "name": "chunk_document",
        "description": "Chunk document with semantic boundaries",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to chunk"},
                "conversation_id": {"type": "string", "description": "Session ID"},
                "strategy": {"type": "string", "description": "Chunking strategy (semantic/heading/fixed)", "default": "semantic"},
                "max_tokens": {"type": "integer", "description": "Max tokens per chunk", "default": 4000},
                "overlap_tokens": {"type": "integer", "description": "Overlap between chunks", "default": 200}
            },
            "required": ["text", "conversation_id"]
        }
    },
    {
        "name": "get_session_status",
        "description": "Get workspace session status",
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string", "description": "Session ID"}
            },
            "required": ["conversation_id"]
        }
    },
    {
        "name": "cleanup_sessions",
        "description": "Cleanup old workspace sessions",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_age_hours": {"type": "integer", "description": "Max age in hours", "default": 24},
                "dry_run": {"type": "boolean", "description": "Dry run mode", "default": True}
            },
            "required": []
        }
    },
    {
        "name": "update_chunk_status",
        "description": "Update chunk processing status",
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string", "description": "Session ID"},
                "chunk_id": {"type": "string", "description": "Chunk ID"},
                "status": {"type": "string", "description": "Status (pending/processing/done/failed)"},
                "summary": {"type": "string", "description": "Summary if done"},
                "error": {"type": "string", "description": "Error if failed"}
            },
            "required": ["conversation_id", "chunk_id", "status"]
        }
    }
]
