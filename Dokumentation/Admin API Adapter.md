# Admin API Adapter Analysis (`adapters/admin-api`)

## Übersicht
Der `admin-api` Adapter fungiert als zentrales Backend für die Jarvis WebUI. Es handelt sich um eine FastAPI-Anwendung, die verschiedene Dienste orchestriert, darunter Chat-Funktionalität (LobeChat-kompatibel), Protokollführung, Workspace-Verwaltung und MCP (Model Context Protocol) Integration.

## Struktur & Module

### 1. `main.py` (Core Application)
- **Funktion**: Einstiegspunkt der Anwendung.
- **Aufgaben**:
    - Initialisiert die FastAPI App (`Jarvis Admin API`).
    - Konfiguriert CORS für den WebUI-Zugriff.
    - Bindet Router ein (`maintenance`, `settings`, `mcp`, `protocol`).
    - **Chat Endpoint (`/api/chat`)**: Handhabt Chat-Anfragen, unterstützt Streaming (via `core.bridge`), und transformiert Datenformate für LobeChat.
    - **Workspace Endpoints (`/api/workspace`)**: CRUD-Operationen für Workspace-Einträge, delegiert an MCP Hub Tools.
    - **Health Check (`/health`)** & **Info (`/`)**.
    - **Ollama Proxy (`/api/tags`)**: Leitet Modellanfragen an die lokale Ollama-Instanz weiter.

### 2. `protocol_routes.py` (Daily Protocol)
- **Funktion**: Verwaltung des täglichen Arbeitsprotokolls (Markdown-basiert).
- **Aufgaben**:
    - Liest/Schreibt Markdown-Dateien in `/app/memory` (Standard).
    - **Features**:
        - Auflisten von Protokollen (`/list`).
        - Heutiges Protokoll abrufen/erstellen (`/today`).
        - Einträge anhängen (`/append`).
        - Manuelles Bearbeiten (`PUT /{date}`).
        - Mergen in den Knowledge Graph (`POST /{date}/merge`).

### 3. `settings_routes.py` (Configuration)
- **Funktion**: Dynamische Verwaltung von Laufzeit-Einstellungen.
- **Aufgaben**:
    - API zum Lesen und Schreiben von Key-Value Settings (via `utils.settings`).

### 4. `requirements.txt` (Dependencies)
- Definiert die notwendigen Python-Pakete (FastAPI, Uvicorn, Requests, etc.).

## Wichtige Imports & Abhängigkeiten

### Externe Bibliotheken
| Bibliothek | Zweck |
|------------|-------|
| `fastapi` | Web Framework (App, Router, StreamingResponse, Middleware). |
| `pydantic` | Datenvalidierung. |
| `requests` | HTTP Calls (z.B. Proxy zu Ollama). |
| `logging` | Standardisiertes Logging (`utils.logger`). |
| `json`, `os`, `re`, `threading` | Standard-Bibliotheken für File-Handling und Concurrency. |

### Interne Module (Antigravity Core)
Das Modul ist stark vernetzt mit dem Kernsystem:

*   **`core.bridge`**: Zugriff auf die KI-Logik (`process`, `process_stream`).
*   **`adapters.lobechat.adapter`**: Transformiert Requests/Responses passend für das LobeChat Frontend.
*   **`mcp.hub`**: Zugriff auf den MCP Hub zur Ausführung von Tools (`workspace_*` Tools, `graph_add_node`).
*   **`mcp.installer`, `mcp.endpoint`**: Router für MCP-Management.
*   **`utils.logger`**: Zentrales Logging.
*   **`utils.settings`**: Globaler Settings-Store.
*   **`maintenance.routes`, `maintenance.persona_routes`**: Eingebundene Router aus dem Maintenance-Modul.

## API Übersicht (Wichtige Endpoints)

- **Chat**: `POST /api/chat` (Streaming Support)
- **Protocol**: 
    - `GET /api/protocol/today`
    - `POST /api/protocol/append`
    - `POST /api/protocol/{date}/merge`
- **Workspace**: 
    - `GET /api/workspace`
    - `PUT /api/workspace/{id}`
- **MCP**: 
    - `POST /mcp` (Tool Call)
    - `POST /api/mcp` (Install/Manage)
- **System**: 
    - `GET /health`
    - `GET /api/tags` (Models)
