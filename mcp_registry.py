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
    # CORE: Storage Broker - Storage governance / policy broker
    # ─────────────────────────────────────────────────────────────
    "storage-broker": {
        "url": os.getenv("MCP_STORAGE_BROKER", "http://storage-broker:8089/mcp"),
        "enabled": os.getenv("ENABLE_MCP_STORAGE_BROKER", "true").lower() == "true",
        "description": "Storage governance broker (disk discovery, zones, policy, audit)",
    },
    
    # ─────────────────────────────────────────────────────────────
    # DEMO: Time MCP
    # ─────────────────────────────────────────────────────────────
    "time-mcp": {
        "command": "python3 -u /app/custom_mcps/time-mcp/server.py",
        "transport": "stdio",
        "path": "/app/custom_mcps/time-mcp",
        "enabled": os.getenv("ENABLE_MCP_TIME_MCP", "true").lower() == "true",
        "description": "Simple Time MCP (STDIO, configurable timezone/country/region)",
    },


}


def get_enabled_mcps() -> Dict[str, Dict[str, Any]]:
    """Gibt nur aktivierte MCPs zurück."""
    return {
        name: config 
        for name, config in MCPS.items() 
        if config.get("enabled") and (config.get("url") or config.get("command"))
    }


def get_mcps() -> Dict[str, Dict[str, Any]]:
    """Backward-compatible full MCP registry snapshot."""
    return dict(MCPS)


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
            "name": "home_start",
            "mcp": "container-commander",
            "description": "Startet oder reused den persistenten TRION Home Container direkt, ohne generischen Blueprint-Router.",
            "arguments": "keine"
        },
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

    # ─────────────────────────────────────────────────────────────
    # STORAGE BROKER TOOLS
    # ─────────────────────────────────────────────────────────────
    if MCPS.get("storage-broker", {}).get("enabled"):
        tools.extend([
            {
                "name": "storage_list_disks",
                "mcp": "storage-broker",
                "description": "Listet erkannte physische Disks und Partitionen inkl. Policy/Zonenstatus.",
                "arguments": "keine"
            },
            {
                "name": "storage_get_summary",
                "mcp": "storage-broker",
                "description": "Gibt Speicher-Übersicht (Anzahlen, Kapazität, Managed/Blocked-Verteilung) zurück.",
                "arguments": "keine"
            },
            {
                "name": "storage_set_disk_zone",
                "mcp": "storage-broker",
                "description": "Setzt Zone für eine Disk/Partition (z. B. managed_services, backup, external).",
                "arguments": "disk_id (str), zone (str)"
            },
            {
                "name": "storage_set_disk_policy",
                "mcp": "storage-broker",
                "description": "Setzt Policy-State für Disk/Partition (blocked, read_only, managed_rw).",
                "arguments": "disk_id (str), policy_state (str)"
            },
            {
                "name": "storage_validate_path",
                "mcp": "storage-broker",
                "description": "Prüft einen Pfad gegen Storage-Policy (inkl. Immutable/System-Guards).",
                "arguments": "path (str)"
            },
            {
                "name": "storage_create_service_dir",
                "mcp": "storage-broker",
                "description": "Erstellt Service-Verzeichnisstruktur in erlaubter Zone (dry_run standardmäßig aktiv).",
                "arguments": "service_name (str), zone (str), profile (str, optional), dry_run (bool, optional)"
            },
        ])

    return tools
