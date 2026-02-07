# Maintenance Module (`maintenance/`)

## Übersicht

Das `maintenance` Modul ist verantwortlich für die **Pflege und Optimierung des Langzeitgedächtnisses** (Memory System) sowie für Verwaltungsfunktionen wie das Persona-Management. Es agiert meist im Hintergrund ("Worker"), kann aber über eine API gesteuert werden.

## Hauptkomponenten

### 1. `worker.py` (MaintenanceWorker)

Der Kern dieses Moduls. Ein asynchroner Worker, der "Hausmeistertätigkeiten" im KI-Gedächtnis durchführt. Er kommuniziert intensiv mit dem `memory` MCP-Server.

**Hauptaufgaben:**

* **Duplikat-Erkennung**: Nutzt ein LLM (Thinking Model), um semantische Duplikate in den Einträgen zu finden und merged diese dann via `memory_delete_bulk`.
* **Promotion (STM → LTM)**: Analysiert Short-Term-Memory Einträge. Wichtige Fakten werden in das Long-Term-Memory (Key-Value Store) "promoted", unwichtiges wird gelöscht.
* **Summarization**: Erstellt Zusammenfassungen von älteren Konversationen, um den Kontext kompakt zu halten.
* **Graph Optimization**:
  * Findet und merged doppelte Knoten im Knowledge Graph.
  * Löscht verwaiste Knoten (Orphans).
  * Entfernt schwache Verbindungen (Pruning).

**Wichtige Funktion**: `unwrap_mcp_result` - Eine robuste Helper-Funktion, um die oft verschachtelten und fehleranfälligen Responses von MCP-Tools sicher zu parsen.

### 2. `routes.py` (API Endpoints)

Stellt die **REST-API** für den Maintenance-Worker bereit (FastAPI Router).

* **Endpoints**:
  * `GET /status`: Liefert den aktuellen Status (Idle/Running) und Memory-Statistiken.
  * `POST /start`: Startet den Maintenance-Prozess (asynchron). Unterstützt Server-Sent Events (SSE) für Live-Progress-Updates im Frontend.
  * `POST /cancel`: Bricht einen laufenden Prozess ab.
  * `POST /clear`: Setzt das gesamte Gedächtnis zurück (Reset).

### 3. `persona_routes.py`

Ein Adapter für das **Persona Management**. Erlaubt das Verwalten von KI-Persönlichkeiten über die API.

* **Funktionen**: List, Get, Upload, Switch, Delete Personas.
* Validiert Persona-Dateien (Größe, Struktur) bevor sie gespeichert werden.

## Abhängigkeiten

* `httpx`: Für Aufrufe an die lokale Ollama LLM API (für KI-Entscheidungen bei der Deduplizierung).
* `fastapi`: Für die API-Routes.
* `mcp.client`: Um Tools des Memory-Systems aufzurufen (`memory_list_conversations`, `graph_merge_nodes`, etc.).
* `core.persona`: Für die Persona-Logik.
