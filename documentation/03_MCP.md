# MCP Modul Dokumentation (`/mcp`)

Das MCP (Model Context Protocol) Modul standardisiert die Art und Weise, wie die KI mit externen Tools und Datenquellen kommuniziert. Es implementiert einen Hub, der verschiedene MCP-Server (wie die Datenbank) verwaltet.

## Wichtige Dateien

-   **`hub.py` (`MCPHub`)**: Die zentrale Klasse, die alle MCP-Verbindungen verwaltet.
-   **`client.py`**: Enthält Hilfsfunktionen für spezifische MCP-Aufrufe (z.B. `get_fact_for_query`).
-   **`transports/`**: Implementierungen der Kommunikationskanäle (z.B. `STDIOTransport`, `HTTPTransport`).
-   **`session.py`**: Verwaltet Sitzungen mit MCP-Servern.

## Der MCP Hub (`hub.py`)

Der `MCPHub` ist (wie die CoreBridge) ein Singleton (`get_hub()`). Er kümmert sich um:

1.  **Transport Management**: Verbindet sich zu konfigurierten MCP-Servern (definiert via `MCPS` config).
2.  **Tool Discovery**: Fragt Server nach verfügbaren Tools (`list_tools`).
3.  **Routing**: Leitet `call_tool(name, args)` an den richtigen Server weiter.
4.  **Auto-Recovery**: Versucht, Verbindungen neu aufzubauen (`refresh`).

### Integration von `sql-memory`

Einer der wichtigsten MCP-Server ist `sql-memory`. Der Hub nutzt diesen, um:
-   Fakten zu speichern (`memory_fact_save`).
-   Wissen abzurufen (`memory_fact_load`, `memory_graph_search`).

Dies geschieht oft transparent über die Helper in `client.py`, die vom Core genutzt werden.

## Protokoll & Transports

Das System unterstützt verschiedene Transport-Arten:
-   **HTTP (SSE)**: Für Server-Dienste wie `validator-service` oder Remote-MCPs.
-   **STDIO**: Startet Subprozesse und kommuniziert über Standard Input/Output (klassischer MCP-Weg für lokale Skripte).

## Wichtige Konzepte

-   **System Conversation ID**: Der Hub nutzt eine spezielle ID (`system`), um internes Wissen zu speichern, das nicht an einen User gebunden ist (z.B. "Welche Tools habe ich?").
-   **Format Detection**: Der Hub versucht automatisch zu erkennen, welches Format ein MCP-Server spricht.

> [!TIP]
> **Debugging**: Der Hub bietet Methoden wie `list_mcps()`, um den Status aller Verbindungen zu prüfen. Nutzen Sie dies, wenn Tools "verschwinden".
