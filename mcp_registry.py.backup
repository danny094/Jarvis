# mcp_registry.py
"""
MCP Registry - Zentrale Konfiguration aller MCPs.

EINFACH: Nur URL eintragen, der Hub erkennt das Format automatisch!

Transport-Types (optional, wird auto-detected):
- http:   HTTP/Streamable HTTP (auto-detected)
- sse:    Legacy SSE-only
- stdio:  Stdin/Stdout (lokale Prozesse)
"""

import os
from typing import Dict, Any

# ═══════════════════════════════════════════════════════════════
# MCP KONFIGURATION
# ═══════════════════════════════════════════════════════════════

MCPS: Dict[str, Dict[str, Any]] = {
    
    # ─────────────────────────────────────────────────────────────
    # CORE: SQL Memory
    # ─────────────────────────────────────────────────────────────
    "sql-memory": {
        "url": os.getenv("MCP_SQL_MEMORY", "http://mcp-sql-memory:8081/mcp"),
        "enabled": True,
        "description": "Persistentes Memory mit Facts, Embeddings und Knowledge Graph",
    },
    
    # ─────────────────────────────────────────────────────────────
    # Sequential Thinking
    # ─────────────────────────────────────────────────────────────
    "sequential-thinking": {
        "url": os.getenv("MCP_SEQUENTIAL", "http://mcp-sequential:8085/mcp"),
        "enabled": True,
        "description": "Sequential Thinking für komplexes Reasoning",
    },
    
    # ─────────────────────────────────────────────────────────────
    # N8N Workflows (wenn aktiviert)
    # ─────────────────────────────────────────────────────────────
    "n8n": {
        "url": os.getenv("MCP_N8N", "http://n8n:5678/mcp/sse"),
        "enabled": os.getenv("ENABLE_MCP_N8N", "false").lower() == "true",
        "description": "N8N Workflow Automation",
    },
    
    # ─────────────────────────────────────────────────────────────
    # OPTIONAL: Code Executor
    # ─────────────────────────────────────────────────────────────
    "code-exec": {
        "url": os.getenv("MCP_CODE_EXEC", "http://mcp-code-exec:8084/mcp"),
        "enabled": os.getenv("ENABLE_MCP_CODE_EXEC", "false").lower() == "true",
        "description": "Sichere Code-Ausführung in Sandbox",
    },
    
    # ─────────────────────────────────────────────────────────────
    # OPTIONAL: STDIO-basierter MCP (lokaler Prozess)
    # ─────────────────────────────────────────────────────────────
    "local-tools": {
        "command": os.getenv("MCP_LOCAL_TOOLS_CMD", ""),
        "transport": "stdio",  # Nur bei STDIO explizit nötig
        "enabled": os.getenv("ENABLE_MCP_LOCAL_TOOLS", "false").lower() == "true",
        "description": "Lokale Tools via STDIO",
    },
    
    # ─────────────────────────────────────────────────────────────
    # CUSTOM: User-definierte MCPs
    # ─────────────────────────────────────────────────────────────
    "custom-1": {
        "url": os.getenv("MCP_CUSTOM_1", ""),
        "enabled": os.getenv("ENABLE_MCP_CUSTOM_1", "false").lower() == "true",
        "api_key": os.getenv("MCP_CUSTOM_1_API_KEY", ""),
        "description": os.getenv("MCP_CUSTOM_1_DESC", "Custom MCP 1"),
    },
    
    "custom-2": {
        "url": os.getenv("MCP_CUSTOM_2", ""),
        "enabled": os.getenv("ENABLE_MCP_CUSTOM_2", "false").lower() == "true",
        "api_key": os.getenv("MCP_CUSTOM_2_API_KEY", ""),
        "description": os.getenv("MCP_CUSTOM_2_DESC", "Custom MCP 2"),
    },
}


def get_enabled_mcps() -> Dict[str, Dict[str, Any]]:
    """Gibt nur aktivierte MCPs zurück."""
    return {
        name: config 
        for name, config in MCPS.items() 
        if config.get("enabled") and (config.get("url") or config.get("command"))
    }


def get_mcp_config(name: str) -> Dict[str, Any]:
    """Gibt Config für ein spezifisches MCP zurück."""
    return MCPS.get(name, {})
