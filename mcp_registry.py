"""
MCP Registry - Zentrale Verwaltung aller MCPs
Definiert welche MCPs aktiv sind und wie sie erreicht werden.
Unterstützte Transports:
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
    # CORE: Sequential Thinking v2.0 (mit CIM Integration)
    # ─────────────────────────────────────────────────────────────
    "sequential-thinking": {
        "url": os.getenv("MCP_SEQUENTIAL_THINKING", "http://sequential-thinking:8085/mcp"),
        "enabled": True,
        "description": "Sequential Thinking Engine v2.0 - Step-by-step reasoning with CIM validation",
    },

    # ─────────────────────────────────────────────────────────────
    # CORE: CIM Server - Frank's Causal Intelligence Module (NEU!)
    # ─────────────────────────────────────────────────────────────
    "cim": {
        "url": os.getenv("MCP_CIM", "http://cim-server:8086/mcp"),
        "enabled": True,
        "description": "Causal Intelligence Module - Graph building, validation, anti-pattern detection",
    },

    # ─────────────────────────────────────────────────────────────
    # CORE: Skill Server - AI Skill Management & Creation
    # ─────────────────────────────────────────────────────────────
    "skill-server": {
        "url": os.getenv("MCP_SKILL_SERVER", "http://trion-skill-server:8088"),
        "enabled": True,
        "description": "AI Skill Studio - Create, validate and manage skills",
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

    # ─────────────────────────────────────────────────────────────
    # DEMO: Time MCP
    # ─────────────────────────────────────────────────────────────
    "time-mcp": {
        "command": "python3 -u /app/custom_mcps/time-mcp/server.py",
        "transport": "stdio",
        "path": "/app/custom_mcps/time-mcp",
        "enabled": False,  # DISABLED - 60s timeout blocker!
        "description": "Simple Time MCP (STDIO)",
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


def list_core_mcps() -> list:
    """Listet alle Core MCPs auf (immer enabled)."""
    return ["sql-memory", "sequential-thinking", "cim"]


# ═══════════════════════════════════════════════════════════════
# TOOL DEFINITIONS (für Dynamic Prompt Injection)
# ═══════════════════════════════════════════════════════════════

def get_enabled_tools() -> list:
    """
    Gibt alle verfügbaren Tools von aktivierten MCPs zurück.
    Wird für System-Prompt Injection genutzt, damit die KI die Tools kennt
    und nicht halluziniert.
    
    Returns:
        List of dicts with tool name and description
    """
    tools = []

    # [NEW] Add Fast Lane Tools (Local Import to avoid circular dependency)
    try:
        from core.tools.fast_lane.definitions import get_fast_lane_tools_summary
        tools.extend(get_fast_lane_tools_summary())
    except ImportError:
        pass
    
    # ─────────────────────────────────────────────────────────────
    # SKILL SERVER TOOLS (Wichtig für autonome Skill-Erstellung!)
    # ─────────────────────────────────────────────────────────────
    if MCPS.get("skill-server", {}).get("enabled"):
        tools.extend([
            {
                "name": "create_skill",
                "mcp": "skill-server",
                "description": "Erstellt einen neuen Skill (Python Code). Nutze dies wenn der User einen Skill/Fähigkeit erstellen möchte.",
                "arguments": "name (str), code (str), description (str), triggers (list)"
            },
            {
                "name": "list_skills",
                "mcp": "skill-server",
                "description": "Listet alle installierten Skills auf.",
                "arguments": "keine"
            },
            {
                "name": "run_skill",
                "mcp": "skill-server",
                "description": "Führt einen installierten Skill aus.",
                "arguments": "name (str), args (dict)"
            },
            {
                "name": "uninstall_skill",
                "mcp": "skill-server",
                "description": "Entfernt einen installierten Skill.",
                "arguments": "name (str)"
            },
            {
                "name": "validate_skill_code",
                "mcp": "skill-server",
                "description": "Prüft Python-Code auf Sicherheitsprobleme.",
                "arguments": "code (str)"
            },
        ])
    
    # ─────────────────────────────────────────────────────────────
    # SEQUENTIAL THINKING TOOLS
    # ─────────────────────────────────────────────────────────────
    if MCPS.get("sequential-thinking", {}).get("enabled"):
        tools.extend([
            {
                "name": "sequentialthinking",
                "mcp": "sequential-thinking",
                "description": "Für komplexe Probleme die schrittweises Nachdenken erfordern.",
                "arguments": "thought (str), nextThoughtNeeded (bool)"
            },
        ])
    
    # ─────────────────────────────────────────────────────────────
    # MEMORY TOOLS
    # ─────────────────────────────────────────────────────────────
    if MCPS.get("sql-memory", {}).get("enabled"):
        tools.extend([
            {
                "name": "store_fact",
                "mcp": "sql-memory",
                "description": "Speichert einen Fakt/Information dauerhaft.",
                "arguments": "key (str), value (str), category (str)"
            },
            {
                "name": "recall_fact",
                "mcp": "sql-memory",
                "description": "Ruft einen gespeicherten Fakt ab.",
                "arguments": "key (str) oder query (str)"
            },
        ])
    
    # ─────────────────────────────────────────────────────────────
    # CIM TOOLS (Causal Intelligence)
    # ─────────────────────────────────────────────────────────────
    if MCPS.get("cim", {}).get("enabled"):
        tools.extend([
            {
                "name": "analyze",
                "mcp": "cim",
                "description": "Analysiert ein Problem kausal (Ursache-Wirkung).",
                "arguments": "query (str), mode (str: light/heavy)"
            },
        ])
    
    # ─────────────────────────────────────────────────────────────
    # CONTAINER COMMANDER TOOLS
    # ─────────────────────────────────────────────────────────────
    tools.extend([
        {
            "name": "request_container",
            "mcp": "container-commander",
            "description": "Startet einen isolierten Container aus einem Blueprint (z.B. python-sandbox, node-sandbox, db-sandbox). Nutze dies wenn Code ausgefuehrt, Daten verarbeitet oder Tools installiert werden sollen.",
            "arguments": "blueprint_id (str), timeout_override (int, optional)"
        },
        {
            "name": "stop_container",
            "mcp": "container-commander",
            "description": "Stoppt einen laufenden Container. IMMER aufrufen wenn du fertig bist!",
            "arguments": "container_id (str)"
        },
        {
            "name": "exec_in_container",
            "mcp": "container-commander",
            "description": "Fuehrt einen Befehl in einem laufenden Container aus und gibt stdout/stderr zurueck.",
            "arguments": "container_id (str), command (str), timeout (int, optional)"
        },
        {
            "name": "blueprint_list",
            "mcp": "container-commander",
            "description": "Listet alle verfuegbaren Container-Blueprints (Sandbox-Typen) auf.",
            "arguments": "tag (str, optional)"
        },
        {
            "name": "container_stats",
            "mcp": "container-commander",
            "description": "Zeigt CPU/RAM/Effizienz eines laufenden Containers.",
            "arguments": "container_id (str)"
        },
        {
            "name": "container_logs",
            "mcp": "container-commander",
            "description": "Holt die Logs eines Containers.",
            "arguments": "container_id (str), tail (int, optional)"
        },
    ])

    return tools
