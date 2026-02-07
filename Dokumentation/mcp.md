# MCP Module (`mcp/`)

## Übersicht

Das **Model Context Protocol (MCP)** ist das zentrale Nervensystem für externe Werkzeuge und Datenquellen. Dieses Verzeichnis enthält die **Implementierung des Hubs**, der alle MCP-Server (Core & Custom) verwaltet, aggregiert und der KI zur Verfügung stellt.

## Hauptkomponenten

### 1. `hub.py` (MCPHub)

Der Singleton-Orchestrator.

- **Aggregation**: Lädt alle konfigurierten MCPs (`mcp_registry.py`).
- **Routing**: Sendet Tool-Calls (`call_tool`) an den korrekten Server.
- **Auto-Registration**: Registriert beim Start alle verfügbaren Tools automatisch im **Knowledge Graph** (`sql-memory`), damit die KI weiß, was sie kann.
- **Protocol Translation**: Handelt die Kommunikation über HTTP, SSE oder STDIO.
- **Detection Rules**: Generiert "Trigger Rules" für den ThinkingLayer, damit Tools proaktiv genutzt werden.

### 2. `client.py`

Eine High-Level Library für den internen Gebrauch.

- **Methoden**: `call_tool`, `autosave_assistant`.
- **Memory Helpers**: Vereinfacht Zugriffe auf das Gedächtnis (`get_fact_for_query`, `semantic_search`, `graph_search`).
- **Fallback**: Wenn der Hub nicht erreichbar ist, versucht er direkte Calls.

### 3. `endpoint.py` (Universal Bridge)

Der einzige Endpoint, den externe WebUIs kennen müssen (`/mcp`).

- **Funktion**: Ein JSON-RPC Gateway.
- **Feature**: Aggregiert ALLE Tools aller verbundenen MCPs in eine einzige Liste. Das Frontend muss nicht wissen, welcher Server was macht.

### 4. `installer.py`

Managed die Installation von neuen MCPs ("Tier 1").

- Erlaubt Upload von ZIP-Dateien mit MCP-Code.
- Validiert `config.json`.
- Installiert Dependencies via `uv pip install`.
- "Hot Reloaded" die Registry ohne Neustart.

### 5. `transports/`

Implementierungen der MCP-Transport-Layer:

- `http.py`: Standard REST Requests.
- `sse.py`: Server-Sent Events für Streaming-Antworten.
- `stdio.py`: Lokale Prozess-Kommunikation (stdin/stdout).

## Abhängigkeiten

- `mcp_registry`: Konfigurationsdatei/Modul für aktive MCPs.
- `requests` / `httpx`: Für HTTP-Kommunikation.
- `fastapi`: Für `endpoint.py` und `installer.py`.
