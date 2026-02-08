# Jarvis Adapter & WebUI Analysis (`adapters/Jarvis`)

## Übersicht

Der **Jarvis Adapter** ist die primäre, "native" Schnittstelle für die Interaktion mit dem Core-System. Er bietet eine hochoptimierte API für das Jarvis Web Frontend und integriert tief liegende Systemkomponenten wie den MCP Hub, Persona-Management und Maintenance-Funktionen. Im Gegensatz zu anderen Adaptern (wie LobeChat) verzichtet dieser auf externe API-Mimikry (z.B. OpenAI-Format) zugunsten interner Effizienz und erweitertem Funktionsumfang.

## Struktur & Module

### 1. `main.py` (Server & Entrypoint)

- **Funktion**: Startet den FastAPI Server.
- **Aufgaben**:
  - **Initialisierung**: Lädt den `MCPHub` beim Start.
  - **Routing**: Bindet Sub-Router ein:
    - `maintenance_endpoints.py` (`/api/maintenance`)
    - `persona_endpoints.py` (`/api/personas`)
    - `mcp.endpoint` (Core MCP Router)
  - **Chat Endpoint (`POST /chat`)**:
    - Zentraler Einstiegspunkt für Nachrichten.
    - Nutzt `JarvisAdapter` zur Datentransformation.
    - Leitet Anfragen an `core.bridge` weiter.
    - Unterstützt Server-Sent Events (SSE) für Streaming (`text/event-stream`).

### 2. `adapter.py` (Logic Adapter)

- **Klasse**: `JarvisAdapter` (erbt von `BaseAdapter`).
- **Funktion**: Übersetzt zwischen dem simplen Jarvis-JSON-Format und den internen `CoreChatRequest`/`CoreChatResponse` Objekten.
- **Formate**:
  - *Request*: `{"query": "...", "conversation_id": "...", "stream": true, ...}`
  - *Response*: `{"response": "...", "done": true, "metadata": {...}}` (oder Streaming Chunks).
- **Besonderheit**: Fügt bei Bedarf System-Kontext in den Nachrichtenverlauf ein.

### 3. `persona_endpoints.py` (Persona Management)

- **Funktion**: REST API für CRUD-Operationen auf KI-Personas.
- **Features**:
  - Auflisten aller Personas (`GET /`).
  - Abrufen einzelner Definitionen (`GET /{name}`).
  - Upload neuer Personas (`POST /` - `.txt` Dateien).
  - Hot-Swap der aktiven Persona (`PUT /switch`).
  - Schutzmechnismus: `default` Persona kann nicht gelöscht werden.
- **Integration**: Greift direkt auf `core.persona` Logik zu.

### 4. `maintenance_endpoints.py` (System Maintenance)

- **Funktion**: Wartungsfunktionen, primär für das Memory-System.
- **Integration**: Kommuniziert via HTTP mit dem `mcp-sql-memory` Microservice (`http://mcp-sql-memory:8081`).
- **Endpoints**:
  - `/status`: Prüft Health des Memory-Services.
  - `/start`: Startet einen Wartungslauf (via MCP Tool Call `maintenance_run`).

### 5. Frontend Assets

- **`index.html`**: Single Page Application Dashboard.
- **`static/` & `js/`**: Client-seitige Logik und Styles.
- **`nginx.conf`**: Konfiguration für Reverse Proxy Deployment.

## Wichtige Imports & Abhängigkeiten

### Externe Bibliotheken

| Bibliothek | Zweck |
|------------|-------|
| `fastapi` | Webserver, Routing, Streaming. |
| `uvicorn` | ASGI Server Runtime. |
| `requests`, `httpx` | HTTP Clients (für interne Service-Calls). |
| `pydantic` | (Indirekt via Shared Schemas) Datenvalidierung. |

### Interne System-Module

| Modul | Verwendungszweck |
|-------|------------------|
| `mcp.hub` | Zentraler Zugriff auf Tools und MCP Server. |
| `core.bridge` | Verbindungsstück zur KI-Engine (Logic Layer). |
| `core.persona` | Verwaltung der KI-Persönlichkeiten. |
| `core.models` | Datentypen (`CoreChatRequest`, `Message`). |
| `adapters.base` | Basisklasse für Adapter-Implementierungen. |
| `utils.logger` | Systemweites Logging. |

## API Zusammenfassung

| Bereich | Methode | Endpoint | Beschreibung |
|---------|---------|----------|--------------|
| **Chat** | `POST` | `/chat` | Haupt-Chat (Streaming & Blocking). |
| **System** | `GET` | `/health` | Status-Check. |
| **Personas** | `GET` | `/api/personas/` | Liste aller Personas. |
| | `POST` | `/api/personas/` | Upload neuer Persona (.txt). |
| | `PUT` | `/api/personas/switch` | Aktive Persona wechseln. |
| **Maint** | `GET` | `/api/maintenance/status` | Memory Service Status. |
| | `POST` | `/api/maintenance/start` | Wartungslauf starten. |
