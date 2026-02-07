# Skill Server (`mcp-servers/skill-server/`)

Der **Skill Server** ist das Herzstück der Erweiterbarkeit von TRION. Er verwaltet nicht nur vorhandene Tools ("Skills"), sondern befähigt die KI auch dazu, **neue Fähigkeiten autonom zu entwickeln**, zu validieren und auszuführen.

## Architektur & Sicherheit

Der Skill Server folgt einem strikten **Proxy-Pattern** zur Sicherheit:

1. **Read-Only Operations**: Listen (`list_skills`) und Lesen (`get_skill_info`) erfolgen direkt oder cached.
2. **Write Operations (Proxy)**: Kritische Aktionen wie `install_skill` oder `create_skill` werden **nicht** lokal ausgeführt. Stattdessen werden sie an den gehärteten **`tool-executor` (Layer 4)** weitergeleitet. Dies verhindert, dass der Skill Server selbst Systemänderungen vornimmt.
3. **Sandbox Execution**: Auch die Ausführung (`run_skill`) wird an den `tool-executor` delegiert, der den Code in einer isolierten Umgebung startet.

### Das "Mini-Control-Layer" (Autonomie)

Eine Besonderheit ist das integrierte `MiniControlLayer` (in `mini_control_layer.py`). Es erlaubt "Autonome Tasks":

1. **Intent Recognition**: Versteht, was der User will.
2. **Skill Discovery**: Sucht zuerst nach einem existierenden Skill.
3. **Auto-Creation**: Wenn kein Skill existiert (und die Komplexität < Threshold ist), generiert es den Code via LLM (`qwen2.5-coder`).
4. **Validation**: Prüft den generierten Code gegen strikte Sicherheitsregeln (`SkillCIMLight`).
5. **Execution**: Installiert und führt den neuen Skill sofort aus.

---

## Wichtige Module

### 1. `server.py`

Der FastAPI-Einstiegspunkt. Definiert die MCP-Tools und API-Endpoints.

* **Tools**: `list_skills`, `run_skill`, `install_skill`, `autonomous_skill_task`.
* **Endpoints**: `/mcp` (JSON-RPC), `/v1/skills` (REST für WebUI).

### 2. `skill_manager.py`

Der "Dumb Proxy".

* Verwaltet die Kommunikation mit dem `tool-executor`.
* Lädt installierte Skills aus der `_registry/installed.json`.
* Leitet `install`/`uninstall`/`run` Requests weiter.

### 3. `mini_control_layer.py`

Die autonome Logik.

* `process_autonomous_task`: Der Haupt-Loop für "Self-Improving AI".
* `_generate_code_with_coder`: Nutzt Ollama (`qwen2.5-coder`) um Python-Code zu schreiben.
* Integriert **CIM-RAG**, um Templates und Best Practices in den Prompt zu laden.

### 4. `skill_cim_light.py`

Der Wächter (Validator).

* **Regel-basiert (Keine KI)**: Nutzt CSV-Dateien für deterministische Checks.
* **Prüfungen**:
  * **Anti-Patterns**: Blockiert `eval()`, `exec()`, `os.system()`, `subprocess`, etc.
  * **Safety Priors**: Erzwingt Prinzipien wie "Input Sanitization" (PRIOR-004) oder "Sandbox Isolation" (PRIOR-001).
* Gibt einen `ValidationResult` Score zurück.

### 5. `cim_rag.py`

Das Gedächtnis für Code-Generierung.

* Lädt CSVs aus `cim_data/` (`skill_templates.csv`, `security_policies.csv`).
* Stellt dem LLM passende Code-Templates und Security-Policies zur Verfügung, damit generierte Skills direkt "compliant" sind.

### 6. `skill_memory.py`

Telemetry-Client.

* Sendet Ausführungs-Metriken (Dauer, Success/Error) an den `mcp-sql-memory` Service.

---

## MCP Tools

| Tool | Beschreibung |
| :--- | :--- |
| **autonomous_skill_task** | **Mächtigstes Tool:** "Mach X". Sucht Skill oder erstellt ihn neu, führt ihn aus. |
| **list_skills** | Listet installierte und verfügbare Skills. |
| **run_skill** | Führt einen Skill mit Argumenten aus (Delegation an Executor). |
| **install_skill** | Installiert einen Skill aus der Registry (Delegation an Executor). |
| **create_skill** | (Intern/Advanced) Erstellt einen Skill aus Code (Delegation an Executor). |
| **validate_skill_code** | Prüft Code gegen Safety-Regeln (Dry-Run). |

## Konfiguration (ENV)

* `EXECUTOR_URL`: URL des Tool Executors (z.B. `http://tool-executor:8000`).
* `OLLAMA_URL`: URL für Code-Generierung (z.B. `http://host.docker.internal:11434`).
* `CODE_GEN_MODEL`: Modell für Coding (Standard: `qwen2.5-coder:3b`).
* `AUTO_CREATE_THRESHOLD`: Bis zu welcher Komplexität (1-10) darf autonom generiert werden? (Standard: `4`).
* `SKILLS_DIR`: Pfad zum Skills-Volume (Standard: `/skills`).
