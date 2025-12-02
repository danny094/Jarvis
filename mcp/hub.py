# mcp/hub.py
"""
MCP Hub - Zentraler Manager für alle MCPs.

Funktionen:
- Aggregiert Tools von allen aktiven MCPs
- Routet Tool-Calls zum richtigen MCP
- Übersetzt zwischen Protokollen (HTTP/SSE/STDIO)
- AUTO-REGISTRATION: Speichert Tool-Infos automatisch im Knowledge Graph
"""

from typing import Dict, Any, List, Optional
from mcp_registry import MCPS, get_enabled_mcps
from mcp.transports import HTTPTransport, SSETransport, STDIOTransport
from utils.logger import log_info, log_error, log_debug, log_warning


class MCPHub:
    """Zentraler Hub für alle MCPs."""
    
    # System conversation_id für Tool-Wissen
    SYSTEM_CONV_ID = "system"
    
    def __init__(self):
        self._transports: Dict[str, Any] = {}
        self._tools_cache: Dict[str, str] = {}  # tool_name → mcp_name
        self._tool_definitions: Dict[str, Dict] = {}  # tool_name → tool_def
        self._initialized = False
        self._tools_registered = False
    
    def initialize(self):
        """Initialisiert alle aktiven MCPs."""
        if self._initialized:
            return
        
        log_info("[MCPHub] Initializing...")
        
        enabled_mcps = get_enabled_mcps()
        log_info(f"[MCPHub] Found {len(enabled_mcps)} enabled MCPs")
        
        for mcp_name, config in enabled_mcps.items():
            try:
                self._init_transport(mcp_name, config)
                self._discover_tools(mcp_name)
            except Exception as e:
                log_error(f"[MCPHub] Failed to init {mcp_name}: {e}")
        
        self._initialized = True
        log_info(f"[MCPHub] Ready with {len(self._tools_cache)} tools from {len(self._transports)} MCPs")
        
        # Auto-Registration im Graph (nach Initialisierung)
        self._auto_register_tools()
    
    def _init_transport(self, mcp_name: str, config: Dict):
        """Erstellt Transport für ein MCP."""
        transport_type = config.get("transport", "http")
        
        if transport_type == "http" or transport_type == "https":
            url = config.get("url", "")
            api_key = config.get("api_key", "")
            self._transports[mcp_name] = HTTPTransport(url, api_key)
            log_debug(f"[MCPHub] {mcp_name}: HTTP transport → {url}")
            
        elif transport_type == "sse":
            url = config.get("url", "")
            api_key = config.get("api_key", "")
            self._transports[mcp_name] = SSETransport(url, api_key)
            log_debug(f"[MCPHub] {mcp_name}: SSE transport → {url}")
            
        elif transport_type == "stdio":
            command = config.get("command", "")
            self._transports[mcp_name] = STDIOTransport(command)
            log_debug(f"[MCPHub] {mcp_name}: STDIO transport → {command}")
    
    def _discover_tools(self, mcp_name: str):
        """Entdeckt Tools von einem MCP."""
        transport = self._transports.get(mcp_name)
        if not transport:
            return
        
        try:
            tools = transport.list_tools()
            
            for tool in tools:
                tool_name = tool.get("name", "")
                if tool_name:
                    self._tools_cache[tool_name] = mcp_name
                    self._tool_definitions[tool_name] = tool
            
            # Log mit erkanntem Format (wenn HTTPTransport)
            format_info = ""
            if hasattr(transport, 'get_format'):
                detected_format = transport.get_format()
                format_info = f" (format={detected_format})"
            
            log_info(f"[MCPHub] {mcp_name}: {len(tools)} tools discovered{format_info}")
            
        except Exception as e:
            log_error(f"[MCPHub] {mcp_name}: Failed to discover tools: {e}")
    
    # ═══════════════════════════════════════════════════════════════
    # AUTO-REGISTRATION: Tool-Wissen im Graph speichern
    # ═══════════════════════════════════════════════════════════════
    
    def _auto_register_tools(self):
        """
        Registriert alle Tools automatisch im Knowledge Graph.
        
        Speichert:
        - available_mcp_tools: Liste aller verfügbaren Tools
        - tool_<name>: Detaillierte Info pro Tool
        - tool_usage_guide: Allgemeine Nutzungsanleitung
        """
        if self._tools_registered:
            return
        
        # Brauchen sql-memory für Graph-Speicherung
        if "sql-memory" not in self._transports:
            log_warning("[MCPHub] sql-memory not available, skipping auto-registration")
            return
        
        memory_transport = self._transports["sql-memory"]
        
        try:
            log_info("[MCPHub] Auto-registering tools in Knowledge Graph...")
            
            # 1. Tool-Übersicht speichern
            tools_overview = self._generate_tools_overview()
            self._save_system_fact(memory_transport, "available_mcp_tools", tools_overview)
            
            # 2. Detaillierte Tool-Infos speichern (nur für Nicht-Memory-Tools)
            for tool_name, tool_def in self._tool_definitions.items():
                # Memory-Tools nicht extra registrieren (sind immer da)
                if tool_name.startswith("memory_"):
                    continue
                
                tool_info = self._generate_tool_info(tool_name, tool_def)
                self._save_system_fact(memory_transport, f"tool_{tool_name}", tool_info)
            
            # 3. Allgemeine Nutzungsanleitung
            usage_guide = self._generate_usage_guide()
            self._save_system_fact(memory_transport, "tool_usage_guide", usage_guide)
            
            self._tools_registered = True
            log_info(f"[MCPHub] Auto-registration complete: {len(self._tool_definitions)} tools registered")
            
        except Exception as e:
            log_error(f"[MCPHub] Auto-registration failed: {e}")
    
    def _generate_tools_overview(self) -> str:
        """Generiert Übersicht aller verfügbaren Tools."""
        tools_by_mcp: Dict[str, List[str]] = {}
        
        for tool_name, mcp_name in self._tools_cache.items():
            if mcp_name not in tools_by_mcp:
                tools_by_mcp[mcp_name] = []
            tools_by_mcp[mcp_name].append(tool_name)
        
        lines = ["Verfügbare MCP-Tools:"]
        for mcp_name, tools in tools_by_mcp.items():
            # Memory-Tools zusammenfassen
            if mcp_name == "sql-memory":
                lines.append(f"• Memory (sql-memory): Fakten speichern/laden, Graph-Suche, Embeddings")
            else:
                config = MCPS.get(mcp_name, {})
                desc = config.get("description", "")
                tool_list = ", ".join(tools)
                lines.append(f"• {mcp_name}: {desc}. Tools: {tool_list}")
        
        return " ".join(lines)
    
    def _generate_tool_info(self, tool_name: str, tool_def: Dict) -> str:
        """Generiert detaillierte Info für ein Tool."""
        mcp_name = self._tools_cache.get(tool_name, "unknown")
        description = tool_def.get("description", "Keine Beschreibung")
        
        # Parameter extrahieren
        params = []
        input_schema = tool_def.get("inputSchema", {})
        properties = input_schema.get("properties", {})
        required = input_schema.get("required", [])
        
        for param_name, param_def in properties.items():
            param_type = param_def.get("type", "any")
            param_desc = param_def.get("description", "")
            is_required = param_name in required
            req_str = "required" if is_required else "optional"
            
            if param_desc:
                params.append(f"{param_name} ({param_type}, {req_str}): {param_desc}")
            else:
                params.append(f"{param_name} ({param_type}, {req_str})")
        
        params_str = "; ".join(params) if params else "keine Parameter"
        
        return f"Tool '{tool_name}' von MCP '{mcp_name}': {description}. Parameter: {params_str}"
    
    def _generate_usage_guide(self) -> str:
        """Generiert allgemeine Tool-Nutzungsanleitung."""
        non_memory_tools = [
            name for name in self._tools_cache.keys() 
            if not name.startswith("memory_")
        ]
        
        if not non_memory_tools:
            return "Aktuell sind nur Memory-Tools verfügbar."
        
        guide_parts = [
            "Tool-Nutzung: Bei komplexen Aufgaben stehen folgende Tools zur Verfügung:",
        ]
        
        for tool_name in non_memory_tools:
            tool_def = self._tool_definitions.get(tool_name, {})
            desc = tool_def.get("description", "")
            guide_parts.append(f"- {tool_name}: {desc}")
        
        guide_parts.append("Nutze diese Tools wenn die Aufgabe es erfordert.")
        
        return " ".join(guide_parts)
    
    def _save_system_fact(self, transport: Any, key: str, value: str):
        """Speichert einen System-Fact im Graph."""
        try:
            result = transport.call_tool("memory_fact_save", {
                "conversation_id": self.SYSTEM_CONV_ID,
                "key": key,
                "value": value
            })
            log_debug(f"[MCPHub] Saved system fact: {key}")
        except Exception as e:
            log_error(f"[MCPHub] Failed to save fact {key}: {e}")
    
    # ═══════════════════════════════════════════════════════════════
    # SYSTEM KNOWLEDGE: Abrufen von System-Wissen
    # ═══════════════════════════════════════════════════════════════
    
    def get_system_knowledge(self, key: str) -> Optional[str]:
        """
        Ruft System-Wissen aus dem Graph ab.
        
        Args:
            key: z.B. "available_mcp_tools", "tool_think", "tool_usage_guide"
        
        Returns:
            Gespeicherter Wert oder None
        """
        self.initialize()
        
        if "sql-memory" not in self._transports:
            return None
        
        try:
            result = self._transports["sql-memory"].call_tool("memory_fact_load", {
                "conversation_id": self.SYSTEM_CONV_ID,
                "key": key
            })
            
            if isinstance(result, dict):
                # Verschiedene Response-Formate handlen
                if "value" in result:
                    return result["value"]
                if "content" in result:
                    content = result["content"]
                    if isinstance(content, list) and content:
                        return content[0].get("text", "")
            
            return None
            
        except Exception as e:
            log_error(f"[MCPHub] Failed to get system knowledge {key}: {e}")
            return None
    
    def search_system_knowledge(self, query: str, limit: int = 5) -> List[str]:
        """
        Sucht im System-Wissen via Graph-Search.
        
        Args:
            query: Suchbegriff
            limit: Max Ergebnisse
        
        Returns:
            Liste von relevanten Inhalten
        """
        self.initialize()
        
        if "sql-memory" not in self._transports:
            return []
        
        try:
            result = self._transports["sql-memory"].call_tool("memory_graph_search", {
                "conversation_id": self.SYSTEM_CONV_ID,
                "query": query,
                "limit": limit
            })
            
            if isinstance(result, dict) and "results" in result:
                return [r.get("content", "") for r in result["results"]]
            
            return []
            
        except Exception as e:
            log_error(f"[MCPHub] System knowledge search failed: {e}")
            return []
    
    # ═══════════════════════════════════════════════════════════════
    # PUBLIC API
    # ═══════════════════════════════════════════════════════════════
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """Gibt aggregierte Tool-Liste aller MCPs zurück."""
        self.initialize()
        return list(self._tool_definitions.values())
    
    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """
        Ruft ein Tool auf.
        Findet automatisch das richtige MCP und übersetzt das Protokoll.
        """
        self.initialize()
        
        mcp_name = self._tools_cache.get(tool_name)
        if not mcp_name:
            log_error(f"[MCPHub] Tool not found: {tool_name}")
            return {"error": f"Tool '{tool_name}' not found in any MCP"}
        
        transport = self._transports.get(mcp_name)
        if not transport:
            log_error(f"[MCPHub] No transport for MCP: {mcp_name}")
            return {"error": f"MCP '{mcp_name}' not available"}
        
        log_info(f"[MCPHub] Calling {tool_name} via {mcp_name}")
        
        try:
            result = transport.call_tool(tool_name, arguments)
            return result
        except Exception as e:
            log_error(f"[MCPHub] Tool call failed: {e}")
            return {"error": str(e)}
    
    def get_mcp_for_tool(self, tool_name: str) -> Optional[str]:
        """Gibt den MCP-Namen für ein Tool zurück."""
        self.initialize()
        return self._tools_cache.get(tool_name)
    
    def list_mcps(self) -> List[Dict[str, Any]]:
        """Gibt Status aller MCPs zurück."""
        self.initialize()
        
        result = []
        for mcp_name, config in MCPS.items():
            transport = self._transports.get(mcp_name)
            
            # Zähle Tools für dieses MCP
            tools_count = sum(1 for t, m in self._tools_cache.items() if m == mcp_name)
            
            # Erkanntes Format (wenn HTTPTransport)
            detected_format = None
            if transport and hasattr(transport, 'get_format'):
                detected_format = transport.get_format()
            
            result.append({
                "name": mcp_name,
                "enabled": config.get("enabled", False),
                "transport": config.get("transport", "http"),
                "detected_format": detected_format,
                "url": config.get("url", "") or config.get("command", ""),
                "description": config.get("description", ""),
                "online": transport.health_check() if transport else False,
                "tools_count": tools_count,
            })
        
        return result
    
    def refresh(self):
        """Aktualisiert Tool-Liste von allen MCPs."""
        log_info("[MCPHub] Refreshing...")
        
        self._tools_cache.clear()
        self._tool_definitions.clear()
        self._tools_registered = False  # Neu registrieren
        
        for mcp_name in self._transports.keys():
            self._discover_tools(mcp_name)
        
        # Re-register nach Refresh
        self._auto_register_tools()
        
        log_info(f"[MCPHub] Refresh complete: {len(self._tools_cache)} tools")
    
    def shutdown(self):
        """Beendet alle STDIO-Transports."""
        for mcp_name, transport in self._transports.items():
            if isinstance(transport, STDIOTransport):
                transport.shutdown()
        log_info("[MCPHub] Shutdown complete")


# ═══════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════

_hub_instance: Optional[MCPHub] = None

def get_hub() -> MCPHub:
    """Gibt die Hub-Singleton-Instanz zurück."""
    global _hub_instance
    if _hub_instance is None:
        _hub_instance = MCPHub()
    return _hub_instance
