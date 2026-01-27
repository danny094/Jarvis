# mcp_registry.py
"""
MCP Registry - Hybrid Core + Custom

Core MCPs: Hardcoded system services (read-only).
Custom MCPs: Loaded dynamically from /app/custom_mcps (or local ./custom_mcps).
"""

import os
import json
from pathlib import Path
from typing import Dict, Any
from utils.logger import log_info, log_error

# 1. CORE MCPs (System-Level, Hardcoded)
CORE_MCPS = {
    "sql-memory": {
        "url": os.getenv("MCP_SQL_MEMORY", "http://mcp-sql-memory:8081/mcp"),
        "transport": "http",
        "enabled": True,
        "tier": "core",
        "description": "SQL-based long-term memory"
    },
    "sequential-thinking": {
        "url": os.getenv("MCP_SEQUENTIAL_THINKING", "http://sequential-thinking:8085/mcp"),
        "transport": "http",
        "enabled": True,
        "tier": "core",
        "description": "Deep reasoning with step-by-step thinking"
    },
    "cim-server": {
        "url": os.getenv("CIM_URL", "http://cim-server:8086/mcp"),
        "transport": "http",
        "enabled": True,
        "tier": "core",
        "description": "Causal Intelligence Module (Frank's Graph)"
    },
    "document-processor": {
        "url": os.getenv("DOCUMENT_PROCESSOR_URL", "http://document-processor:8087/mcp"),
        "transport": "http",
        "enabled": True,
        "tier": "core",
        "description": "Document Processing & Chunking Service"
    }
}

def load_custom_mcps() -> Dict[str, Any]:
    """
    Scan custom_mcps directory for config.json files.
    
    Structure:
    /app/custom_mcps/
      my-tool/
        config.json
      another-tool/
        config.json
    """
    custom = {}
    
    # Try multiple paths for local dev vs docker
    possible_paths = [
        Path("/app/custom_mcps"),
        Path("./custom_mcps"),
        Path(os.getcwd()) / "custom_mcps"
    ]
    
    custom_dir = None
    for p in possible_paths:
        if p.exists() and p.is_dir():
            custom_dir = p
            break
            
    if not custom_dir:
        # log_info("[Registry] No custom_mcps directory found.")
        return custom
    
    # log_info(f"[Registry] Scanning {custom_dir} for Custom MCPs...")
    
    for mcp_dir in custom_dir.iterdir():
        if not mcp_dir.is_dir():
            continue
        
        config_file = mcp_dir / "config.json"
        if not config_file.exists():
            continue
        
        try:
            content = config_file.read_text()
            if not content.strip():
                continue
                
            config = json.loads(content)
            
            # Validate required fields
            if "name" not in config or "url" not in config:
                log_error(f"[Registry] Skipping {mcp_dir.name}: Missing name or url in config.json")
                continue
                
            name = config["name"]
            
            # Enforce metadata
            config["tier"] = config.get("tier", "custom")  # Default to custom
            config["source"] = "custom"
            config["local_path"] = str(mcp_dir)
            
            custom[name] = config
            # log_info(f"[Registry] Found Custom MCP: {name} ({config.get('tier')})")
            
        except Exception as e:
            log_error(f"[Registry] Failed to load {mcp_dir.name}: {e}")
    
    return custom


def get_mcps() -> Dict[str, Any]:
    """
    Get all registered MCPs (Core + Custom).
    Called dynamically to support Hot Reloading.
    """
    # 1. Start with Core
    mcps = CORE_MCPS.copy()
    
    # 2. Merge Custom (Override Core if name conflicts? Or prevent?)
    # Policy: Custom CANNOT override Core
    custom = load_custom_mcps()
    
    for name, config in custom.items():
        if name in mcps:
            log_error(f"[Registry] Conflict: Custom MCP '{name}' tries to override Core MCP. Ignoring.")
            continue
        mcps[name] = config
        
    # 3. Filter disabled
    active_mcps = {
        name: config
        for name, config in mcps.items()
        if config.get("enabled", True)
    }
    
    return active_mcps

# For backward compatibility (if anything imports MCPS directly)
# Deprecated: usage should switch to get_mcps()
MCPS = get_mcps()
