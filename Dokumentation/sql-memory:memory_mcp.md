# Memory MCP Core (`sql-memory/memory_mcp/`)

Dieses Verzeichnis enthält die **Python-Implementierung** des SQL Memory MCP Servers. Hier liegt der Code, der im Docker-Container ausgeführt wird.

## Kern-Module

### Server & Tools

* **`server.py`**:
  * Der Entry-Point.
  * Initialisiert die Datenbank (`init_db`, `migrate_db`).
  * Startet den `FastMCP` Server auf Port 8081.
* **`tools.py`**:
  * Definiert alle MCP-Tools (`memory_save`, `memory_search`, `maintenance_run`, etc.).
  * Leitet die Aufrufe an `database.py` oder `maintenance_ai.py` weiter.

### Daten-Ebene

* **`database.py`**:
  * Der "Data Access Layer" (DAL).
  * Enthält rohes SQL (`CREATE TABLE`, `INSERT`, `SELECT`) für SQLite.
  * Verwaltet Tabellen für `memory`, `facts`, `workspace_entries` und `graph_*`.
* **`config.py`**:
  * Lädt Environment Variables (z.B. `DB_PATH`).
  * Definiert statische Keyword-Listen für `auto_layer.py`.

### AI & Maintenance

* **`maintenance_ai.py`**:
  * Der Hauptprozess für die nächtliche Wartung.
  * Iteriert über STM-Einträge, ruft LLMs auf, führt Datenbank-Updates durch.
* **`ai_helpers.py`**:
  * `call_ollama()`: Wrapper für HTTP-Requests an die Ollama API.
  * `parse_ai_decision()`: Parst die textuelle Antwort des LLMs in ein Python-Dict (`decision`, `confidence`, `reasoning`).
  * `write_conflict_log()`: Schreibt Protokolle, wenn Primary-Model und Validator uneinig sind.
* **`ai_prompts.py`**:
  * Enthält die System-Prompts für die LLMs (z.B. `PROMOTION_PROMPT`, `DUPLICATE_PROMPT`).
  * Hier wird definiert, *wie* die KI entscheiden soll (Kriterien für LTM vs STM).

### Utilities

* **`auto_layer.py`**:
  * Eine Heuristik für die *sofortige* Layer-Zuweisung beim Speichern (bevor die AI drüberläuft).
  * Regeln:
    * System-Prompt $\to$ **LTM**
    * Kurzer Text (< 80 Zeichen) $\to$ **STM**
    * Keywords ("project", "todo") $\to$ **MTM**
    * Keywords ("always", "preference") $\to$ **LTM**

---

## Ablauf der Maintenance (vereinfacht)

1. **Trigger**: `tools.maintenance_run()` wird aufgerufen (manuell oder per Scheduler).
2. **Logic**: `maintenance_ai.py` übernimmt.
3. **Phase 1 (Promotion)**:
    * Lädt STM-Einträge aus `database.py`.
    * Baut Prompt mit `ai_prompts.PROMOTION_PROMPT`.
    * Fragt LLM via `ai_helpers.call_ollama()`.
    * (Optional) Fragt Validator-LLM.
    * Bei Erfolg: Update `layer='ltm'` in DB.
4. **Phase 2 (Deduplication)**:
    * Sucht doppelte Inhalte via SQL.
    * Löscht Redundanzen.
5. **Phase 3 (Graph)**:
    * Löscht isolierte Knoten.
