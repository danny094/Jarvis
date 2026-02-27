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
from mcp_registry import MCPS, get_enabled_mcps, get_mcp_config
from mcp.transports import HTTPTransport, SSETransport, STDIOTransport

from utils.logger import log_info, log_error, log_debug, log_warning
import json
import os
import threading
from pathlib import Path



# ─────────────────────────────────────────────────────────────────────────────
# TOOL KEYWORDS: Enriched Keywords für bessere Semantic-Search-Treffsicherheit.
# Jede Eintragung erweitert den gespeicherten Content beim Auto-Registration.
# ─────────────────────────────────────────────────────────────────────────────
TOOL_KEYWORDS: Dict[str, List[str]] = {
    # SysInfo
    "get_system_info": [
        "GPU", "VRAM", "CPU", "RAM", "Arbeitsspeicher", "Disk", "Festplatte",
        "Temperatur", "Hardware", "nvidia", "Prozessor", "Auslastung",
        "Netzwerk", "Ports", "Docker-Status", "Uptime", "Kernel", "dmesg",
    ],
    "get_system_overview": [
        "System", "Übersicht", "Hardware", "Status", "GPU", "CPU", "RAM", "Disk",
        "alle Infos", "Zusammenfassung",
    ],
    # Container Commander
    "request_container": [
        "Container", "starten", "erstellen", "Python", "Code ausführen",
        "Sandbox", "deployen", "aufsetzen", "neuen Container",
    ],
    "stop_container": [
        "Container", "stoppen", "beenden", "löschen", "herunterfahren",
    ],
    "exec_in_container": [
        "Code", "ausführen", "Container", "Python", "Script", "Command",
        "Bash", "Shell", "Terminal", "run",
    ],
    "container_logs": [
        "Logs", "Container", "Ausgabe", "Output", "Fehler", "Error", "Log",
    ],
    "container_stats": [
        "Container", "Stats", "Status", "läuft", "aktiv", "Ressourcen",
    ],
    "container_list": [
        "Container", "auflisten", "alle Container", "welche Container", "laufende Container", "list containers",
    ],
    "container_inspect": [
        "Container", "inspizieren", "Details", "Konfiguration", "Container-Info", "inspect",
    ],
    "blueprint_list": [
        "Blueprint", "Container-Typen", "verfügbare Typen", "Vorlagen",
    ],
    "blueprint_get": ["Blueprint", "Details", "Konfiguration"],
    "blueprint_create": ["Blueprint", "erstellen", "neue Vorlage"],
    "snapshot_list": ["Snapshot", "Backup", "Versionen", "gespeichert"],
    "snapshot_restore": ["Snapshot", "wiederherstellen", "zurücksetzen"],
    "optimize_container": ["Container", "optimieren", "Performance", "tuning"],
    # Skills
    "list_skills": [
        "Skills", "auflisten", "installiert", "verfügbar", "was kann ich",
        "Fähigkeiten",
    ],
    "run_skill": [
        "Skill", "ausführen", "starten", "verwenden", "benutzen",
    ],
    "create_skill": [
        "Skill", "erstellen", "bauen", "programmieren", "neu schreiben",
        "implementieren",
    ],
    "autonomous_skill_task": [
        "Skill", "automatisch", "eigenständig", "selbst erstellen",
        "Aufgabe erledigen", "reparieren", "verbessern",
    ],
    "promote_skill_draft": [
        "Skill", "veröffentlichen", "promoten", "Draft aktivieren",
    ],
    # Home / Dateien (Fast Lane)
    "home_read": [
        "Datei", "lesen", "öffnen", "Inhalt anzeigen", "Notiz lesen", "was steht",
    ],
    "home_write": [
        "Datei", "schreiben", "speichern", "Notiz", "erstellen", "notieren",
        "aufschreiben", "festhalten",
    ],
    "home_list": [
        "Dateien", "auflisten", "Verzeichnis", "Ordner", "welche Dateien",
    ],
    # Memory / Knowledge
    "memory_save": [
        "merken", "speichern", "Fakt", "Notiz", "wissen", "nicht vergessen",
    ],
    "memory_search": [
        "suchen", "finden", "erinnern", "Erinnerung", "was weiß ich",
        "gespeichert", "Fakten",
    ],
    "memory_graph_search": [
        "Graph", "Wissen", "Zusammenhang", "verbunden", "Beziehung",
    ],
    # Workspace — editierbare Einträge (sql-memory)
    "workspace_save": [
        "Workspace", "Notiz", "Task", "Aufgabe merken", "Plan speichern", "Eintrag erstellen",
    ],
    "workspace_list": [
        "Workspace", "Einträge anzeigen", "offene Aufgaben", "Was habe ich geplant",
    ],
    # Workspace Events — interne Telemetrie (Fast-Lane, read-only)
    "workspace_event_save": [
        "Workspace-Event", "Telemetrie", "Container-Event speichern", "internes Ereignis",
    ],
    "workspace_event_list": [
        "Workspace-Events", "Container-Status", "aktive Container", "Event-Log lesen",
    ],
    # Skill-Metriken
    "skill_metric_record": ["Skill", "Metriken", "Statistik", "aufzeichnen"],
    "skill_metrics_list": ["Skill", "Statistiken", "Übersicht", "Metriken"],
    # Graph
    "graph_add_node": ["Graph", "Knoten", "Wissen", "speichern", "Relation"],
}


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
        self._lock = threading.RLock()


    def _register_fast_lane_tools(self):
        """
        Register Fast Lane Tools in Knowledge Graph
        
        CRITICAL: Without this, Tool Selector cannot find Fast Lane tools!
        """
        try:
            from core.tools.fast_lane.definitions import get_fast_lane_tools_summary
            
            fast_lane_tools = get_fast_lane_tools_summary()
            
            log_info(f"[MCPHub] Registering {len(fast_lane_tools)} Fast Lane tools...")
            
            for tool in fast_lane_tools:
                # Add execution metadata
                tool["execution"] = "direct"  # Mark as direct execution
                tool["mcp"] = "fast-lane"     # Pseudo-MCP name
                
                # Register in tool registry
                self._tool_definitions[tool["name"]] = tool
                self._tools_cache[tool["name"]] = "fast-lane"
                
                # Register in Knowledge Graph (for Tool Selector semantic search)
                self._register_tool_in_graph(tool)
                
                log_info(f"[MCPHub] ✓ Registered Fast Lane tool: {tool['name']}")
            
            log_info(f"[MCPHub] Fast Lane tools registered successfully!")
            
        except Exception as e:
            log_error(f"[MCPHub] Failed to register Fast Lane tools: {e}")


    def _register_tool_in_graph(self, tool: dict):
        """
        Register tool in Knowledge Graph for Tool Selector
        
        This makes tools searchable via semantic search!
        """
        try:
            # Prepare tool documentation
            tool_doc = {
                "tool_name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters", {}),
                "execution": tool.get("execution", "mcp"),
                "mcp": tool.get("mcp", "unknown"),
            }
            
            # Convert to searchable text (for embeddings)
            searchable_text = f"{tool['name']}: {tool.get('description', '')}"
            
            # Store in Knowledge Graph via memory_mcp
            # This enables Tool Selector's semantic search!
            # Using call_tool self-reference might be tricky if not initialized, 
            # but memory_mcp should be there.
            if "sql-memory" in self._transports:
                 self._transports["sql-memory"].call_tool("memory_graph_save", {
                    "node_type": "tool",
                    "node_id": tool["name"],
                    "properties": tool_doc,
                    "searchable_text": searchable_text,
                    "content_type": "tool",  # CRITICAL: Tool Selector filters by this!
                })
                
            log_info(f"[MCPHub] Tool registered in Knowledge Graph: {tool['name']}")
            
        except Exception as e:
            # Don't fail if graph registration fails
            log_warning(f"[MCPHub] Could not register tool in graph (non-critical): {e}")
    
    def initialize(self):
        """Initialisiert alle aktiven MCPs."""
        with self._lock:
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
            

            # Register Container Commander tools (local, no HTTP)
            try:
                from container_commander.mcp_bridge import register_commander_tools
                register_commander_tools(self)
            except Exception as e:
                log_warning(f"[MCPHub] Container Commander not available: {e}")

            # Register SysInfo tools (read-only system diagnostics, allowlist-based)
            try:
                from sysinfo.mcp_bridge import register_sysinfo_tools
                register_sysinfo_tools(self)
            except Exception as e:
                log_warning(f"[MCPHub] SysInfo not available: {e}")
            self._initialized = True
            log_info(f"[MCPHub] Ready with {len(self._tools_cache)} tools from {len(self._transports)} MCPs")

            # Register Fast Lane tools as early as possible after MCP discovery.
            # This keeps runtime-only tools (workspace_event_*) immediately callable,
            # even if graph auto-registration is slow.
            self._register_fast_lane_tools()

            # Auto-Registration im Graph (best effort, may be slow under load)
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
    # DETECTION RULES: Generierung von Rules für ThinkingLayer
    # ═══════════════════════════════════════════════════════════════

    def _get_mcp_config(self, mcp_name: str) -> Optional[Dict]:
        """
        Lädt config.json für einen MCP.
        Strategie:
        1. 'path' aus mcp_registry.json
        2. Fallback: /app/custom_mcps/<mcp_name>/config.json
        """
        try:
            # 1. Check Registry Path
            config_path = None
            # SAFE ACCESS: Use helper or handle potential NameError if MCPS is missing
            try:
                mcp_info = get_mcp_config(mcp_name)
            except NameError:
                 # Fallback if import failed
                from mcp_registry import get_mcp_config as _get_conf
                mcp_info = _get_conf(mcp_name)

            if mcp_info and "path" in mcp_info:
                path_str = mcp_info["path"]
                if path_str:
                    potential_path = Path(path_str) / "config.json"
                    if potential_path.exists():
                        config_path = potential_path
            
            # 2. Fallback Custom MCP Path
            if not config_path:
                fallback_path = Path(f"/app/custom_mcps/{mcp_name}/config.json")
                if fallback_path.exists():
                    config_path = fallback_path
            
            if config_path:
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
                    
        except Exception as e:
            log_warning(f"[MCPHub] Invalid config for {mcp_name}: {e}")
            
        return None

    def _generate_detection_rules(self) -> str:
        """
        Generiert Detection Rules für den ThinkingLayer.
        Liest detection Block aus config.json aller Custom MCPs.
        Inkludiert auch Core MCP Rules für Memory Tools.
        """
        rules = []
        
        # CORE MCP DETECTION RULES (hardcoded für sql-memory)
        core_memory_rules = """
TOOL: memory_save (MCP: sql-memory)
Priority: high
Keywords: remember, save, store, note, keep in mind, merken, speichern, notieren
Triggers: remember that, save this, note that, please remember, bitte merken
Examples: User: Remember my favorite color is blue -> memory_save

TOOL: memory_graph_search (MCP: sql-memory)
Priority: high
Keywords: recall, remember, what do you know, search memory, erinnern, was weisst du
Triggers: do you remember, what did I say, what do you know about, was habe ich gesagt
Examples: User: What is my favorite color? -> memory_graph_search

TOOL: memory_all_recent (MCP: sql-memory)
Priority: medium
Keywords: recent memories, last conversations, previous chats, letzte gespraeche
Triggers: what did we talk about, show recent memories
Examples: User: What did we discuss yesterday? -> memory_all_recent
"""
        rules.append((0, core_memory_rules))

        # CORE CONTAINER COMMANDER DETECTION RULES
        core_commander_rules = """
TOOL: blueprint_list (MCP: container-commander)
Priority: high
Keywords: blueprint, blueprints, container-typ, sandbox, container typen, welche container, verfügbare container
Triggers: zeig blueprints, welche blueprints, list blueprints, was für container gibt es, verfügbare sandboxes
Examples: User: Welche Blueprints hast du? -> blueprint_list; User: Was für Container gibt es? -> blueprint_list

TOOL: request_container (MCP: container-commander)
Priority: high
Keywords: starte container, deploy, container starten, brauche sandbox, code ausführen, python starten, node starten
Triggers: starte einen container, deploy blueprint, ich brauche einen container, führe code aus
Examples: User: Starte einen Python Container -> request_container; User: Ich brauche eine Sandbox -> request_container

TOOL: stop_container (MCP: container-commander)
Priority: high
Keywords: stoppe container, stop container, beende container, container beenden, container stoppen
Triggers: stoppe den container, beende den container, container runterfahren
Examples: User: Stoppe den Container -> stop_container

TOOL: exec_in_container (MCP: container-commander)
Priority: high
Keywords: ausführen, execute, run code, berechne, programmiere, führe aus, code ausführen
Triggers: führe diesen code aus, berechne fibonacci, execute in container
Examples: User: Berechne die Fibonacci-Folge -> request_container + exec_in_container

TOOL: container_stats (MCP: container-commander)
Priority: medium
Keywords: container stats, container status, auslastung, efficiency, resource usage
Triggers: wie läuft der container, container auslastung, zeig container stats
Examples: User: Wie ist die Container-Auslastung? -> container_stats

TOOL: container_list (MCP: container-commander)
Priority: medium
Keywords: alle container, laufende container, welche container laufen, container auflisten, list containers
Triggers: zeig alle container, welche container sind aktiv, liste container auf
Examples: User: Welche Container laufen gerade? -> container_list; User: Liste alle aktiven Container -> container_list

TOOL: container_inspect (MCP: container-commander)
Priority: medium
Keywords: container details, container info, container konfiguration, inspiziere container, inspect container
Triggers: zeig container details, was ist die konfiguration des containers, inspect container
Examples: User: Zeig mir die Details von Container abc123 -> container_inspect

TOOL: container_logs (MCP: container-commander)
Priority: medium
Keywords: container logs, container ausgabe, log output
Triggers: zeig container logs, was hat der container ausgegeben
Examples: User: Zeig mir die Container Logs -> container_logs
"""
        rules.append((0, core_commander_rules))

        # CUSTOM MCP DETECTION RULES (aus config.json)
        for mcp_name in self._transports.keys():
            if mcp_name in ["sql-memory", "sequential-thinking", "cim-server"]:
                continue
                
            config = self._get_mcp_config(mcp_name)
            if not config or "detection" not in config:
                continue
            
            detection = config["detection"]
            for tool_name, rule in detection.items():
                keywords = rule.get("keywords", [])
                triggers = rule.get("triggers", [])
                examples = rule.get("examples", [])
                priority = rule.get("priority", "medium")
                
                rule_text = f"""
TOOL: {tool_name} (MCP: {mcp_name})
Priority: {priority}
Keywords: {", ".join(keywords)}
Triggers: {", ".join(triggers[:3])}
Examples: {"; ".join(examples[:2])}
"""
                score = 1
                if str(priority).lower() == "high": score = 0
                elif str(priority).lower() == "low": score = 2
                
                rules.append((score, rule_text))
        
        rules.sort(key=lambda x: x[0])
        final_rules = [r[1] for r in rules]
        
        count = len(final_rules)
        if count > 0:
            log_info(f"[MCPHub] Generated detection rules for {count} tools (incl. core)")
            return "=== MCP DETECTION RULES ===\n" + "\n".join(final_rules)
        
        return "No MCP detection rules available."


    def _get_tool_registry_version(self) -> str:
        """Erstellt einen Versions-Hash aus der aktuellen Tool-Liste."""
        import hashlib
        tool_names = sorted(self._tool_definitions.keys())
        version_str = f"{len(tool_names)}:{','.join(tool_names)}"
        return hashlib.md5(version_str.encode()).hexdigest()[:12]

    def _auto_register_tools(self):
        """
        Registriert alle Tools automatisch im Knowledge Graph.
        Nutzt einen Versions-Hash: Re-Registrierung nur wenn sich Tools geändert haben.
        Verhindert so Duplikate bei Container-Neustarts.

        Speichert:
        - available_mcp_tools: Liste aller verfügbaren Tools
        - tool_<name>: Detaillierte Info pro Tool (mit enriched Keywords)
        - tool_usage_guide: Allgemeine Nutzungsanleitung
        """
        if self._tools_registered:
            return

        # Brauchen sql-memory für Graph-Speicherung
        if "sql-memory" not in self._transports:
            log_warning("[MCPHub] sql-memory not available, skipping auto-registration")
            return

        memory_transport = self._transports["sql-memory"]
        current_version = self._get_tool_registry_version()

        # Version-Check: bereits mit dieser Tool-Konfiguration registriert?
        try:
            stored = memory_transport.call_tool("memory_fact_load", {
                "conversation_id": self.SYSTEM_CONV_ID,
                "key": "tool_registry_version",
            })
            if isinstance(stored, dict):
                stored_version = (
                    stored.get("result") or
                    stored.get("value") or
                    stored.get("structuredContent", {}).get("value", "")
                )
            else:
                stored_version = ""
            if stored_version == current_version:
                log_info(f"[MCPHub] Tool-Registry aktuell (v{current_version}) — keine Re-Registrierung")
                self._tools_registered = True
                return
            log_info(f"[MCPHub] Tool-Registry veraltet ({stored_version} → {current_version}) — aktualisiere...")
        except Exception:
            log_info("[MCPHub] Kein gespeicherter Registry-Stand — Erstregistrierung...")

        try:
            log_info("[MCPHub] Auto-registering tools in Knowledge Graph...")

            # 1. Tool-Übersicht speichern
            tools_overview = self._generate_tools_overview()
            self._save_system_fact(memory_transport, "available_mcp_tools", tools_overview)

            # 2. Detaillierte Tool-Infos mit enriched Keywords (nur Nicht-Memory-Tools)
            for tool_name, tool_def in self._tool_definitions.items():
                if tool_name.startswith("memory_"):
                    continue
                tool_info = self._generate_tool_info(tool_name, tool_def)
                self._save_system_fact(memory_transport, f"tool_{tool_name}", tool_info)

            # 3. Allgemeine Nutzungsanleitung
            usage_guide = self._generate_usage_guide()
            self._save_system_fact(memory_transport, "tool_usage_guide", usage_guide)

            # 4. Detection Rules für Custom MCPs
            detection_rules = self._generate_detection_rules()
            self._save_system_fact(memory_transport, "mcp_detection_rules", detection_rules)

            # 5. Version persistieren — verhindert Re-Registrierung beim nächsten Start
            self._save_system_fact(memory_transport, "tool_registry_version", current_version)

            self._tools_registered = True
            log_info(f"[MCPHub] Auto-registration complete: {len(self._tool_definitions)} tools (v{current_version})")

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
                config = self._get_mcp_config(mcp_name) or {}
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

        base = f"Tool '{tool_name}' von MCP '{mcp_name}': {description}. Parameter: {params_str}"

        # Enriched Keywords für bessere Semantic-Search-Treffsicherheit
        keywords = TOOL_KEYWORDS.get(tool_name)
        if keywords:
            base += f". Keywords: {', '.join(keywords)}"

        return base
    
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
        with self._lock:
            return list(self._tool_definitions.values())
    
    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """
        Ruft ein Tool auf.
        Findet automatisch das richtige MCP und übersetzt das Protokoll.
        Unterstützt auch Fast Lane direct execution.
        """
        self.initialize()
        trace_id = ""
        if isinstance(arguments, dict):
            trace_id = str(arguments.get("_trace_id") or "").strip()
        trace_suffix = f" trace={trace_id}" if trace_id else ""

        # Snapshot routing data under lock so refresh() cannot expose transient empty caches.
        with self._lock:
            tool_def = self._tool_definitions.get(tool_name)
            mcp_name = self._tools_cache.get(tool_name)
            transport = self._transports.get(mcp_name) if mcp_name else None

        # Check if it's a Fast Lane tool (direct execution)
        if tool_def and tool_def.get("execution") == "direct":
            log_info(f"[MCPHub] Calling Fast Lane tool: {tool_name}{trace_suffix}")
            try:
                from core.tools.fast_lane.executor import FastLaneExecutor
                executor = FastLaneExecutor()
                result = executor.execute(tool_name, arguments)
                return result
            except Exception as e:
                log_error(f"[MCPHub] Fast Lane execution failed{trace_suffix}: {e}")
                return {"error": f"Fast Lane execution failed: {e}"}
        
        # Regular MCP tool execution
        if not mcp_name:
            log_error(f"[MCPHub] Tool not found: {tool_name}{trace_suffix}")
            return {"error": f"Tool '{tool_name}' not found in any MCP"}
        
        if not transport:
            log_error(f"[MCPHub] No transport for MCP: {mcp_name}{trace_suffix}")
            return {"error": f"MCP '{mcp_name}' not available"}
        
        log_info(f"[MCPHub] Calling {tool_name} via {mcp_name}{trace_suffix}")
        
        try:
            result = transport.call_tool(tool_name, arguments)
            return result
        except Exception as e:
            log_error(f"[MCPHub] Tool call failed{trace_suffix}: {e}")
            return {"error": str(e)}
    
    def get_mcp_for_tool(self, tool_name: str) -> Optional[str]:
        """Gibt den MCP-Namen für ein Tool zurück."""
        self.initialize()
        with self._lock:
            return self._tools_cache.get(tool_name)
    
    def list_mcps(self) -> List[Dict[str, Any]]:
        """Gibt Status aller MCPs zurück."""
        self.initialize()

        with self._lock:
            transports = dict(self._transports)
            tools_cache = dict(self._tools_cache)

        result = []
        for mcp_name, config in MCPS.items():
            transport = transports.get(mcp_name)
            
            # Zähle Tools für dieses MCP
            tools_count = sum(1 for _, m in tools_cache.items() if m == mcp_name)
            
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
        with self._lock:
            log_info("[MCPHub] Refreshing...")
            
            self._tools_cache.clear()
            self._tool_definitions.clear()
            self._tools_registered = False  # Neu registrieren

            for mcp_name in list(self._transports.keys()):
                self._discover_tools(mcp_name)

            # Keep Fast-Lane tools available immediately after refresh, independent
            # of graph auto-registration runtime.
            self._register_fast_lane_tools()
            # Re-register nach Refresh
            self._auto_register_tools()
            
            tools_count = len(self._tools_cache)
        
        log_info(f"[MCPHub] Refresh complete: {tools_count} tools")
    
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
