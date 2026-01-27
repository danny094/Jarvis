# utils/__init__.py
"""
Utility modules for JARVIS TRION.
"""

from .logger import log_debug, log_error, log_info, log_warn

from .workspace import (
    WorkspaceManager,
    get_workspace_manager,
    SessionMeta,
    ChunkData,
    SessionStatus,
    ChunkStatus,
    quick_session,
    quick_chunk_save,
)

from .chunker import (
    Chunker,
    TextChunk,
    ChunkType,
    count_tokens,
    needs_chunking,
    quick_chunk,
    chunk_for_processing,
    get_chunk_stats,
    CHUNKING_THRESHOLD,
    # v2 - Document Analysis
    DocumentStructure,
    analyze_document_structure,
    quick_document_summary,
)

__all__ = [
    # Logger
    "log_debug",
    "log_error", 
    "log_info",
    "log_warn",
    # Workspace
    "WorkspaceManager",
    "get_workspace_manager",
    "SessionMeta",
    "ChunkData",
    "SessionStatus",
    "ChunkStatus",
    "quick_session",
    "quick_chunk_save",
    # Chunker
    "Chunker",
    "TextChunk",
    "ChunkType",
    "count_tokens",
    "needs_chunking",
    "quick_chunk",
    "chunk_for_processing",
    "get_chunk_stats",
    "CHUNKING_THRESHOLD",
    # Document Analysis
    "DocumentStructure",
    "analyze_document_structure",
    "quick_document_summary",
]
