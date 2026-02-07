# Sequential Thinking Server (`mcp-servers/sequential-thinking/`)

Der **Sequential Thinking Server (v3.0)** ist die Reasoning-Engine von TRION. In der Version 3.0 wurde die Architektur massiv vereinfacht und auf **Frank's CIM Design** umgestellt.

## Architektur (v3.0)

Anstatt eines anfälligen Loops mit vielen kleinen LLM-Calls, setzt v3.0 auf **einen einzigen, mächtigen Reasoning-Call**, der einem strikten Plan folgt.

### Der 3-Phasen-Prozess

1. **Phase 0: Memory Retrieval (Dynamic RAG)**
    * Der Server fragt zuerst den `mcp-sql-memory` Server (`memory_graph_search` oder `semantic_search`).
    * Er sammelt Fakten über das Thema (z.B. "Wer ist User X?", "Was ist Project Y?").
    * Diese Fakten werden als `=== MEMORY CONTEXT ===` in den System-Prompt injiziert.

2. **Phase 1: CIM Analysis (The Roadmap)**
    * Der Server ruft den `cim-server` (`analyze`-Tool).
    * CIM liefert keinen Text, sondern eine **Reasoning Roadmap** (Kausaler Graph).
    * Beispiel: "1. Analysiere Input -> 2. Prüfe Sicherheits-Policies -> 3. Generiere Code -> 4. Validiere".
    * Diese Roadmap wird als `=== CIM CAUSAL CONTEXT ===` injiziert.

3. **Phase 2: Single-Shot Execution**
    * Ein **einziger** Call an Ollama (z.B. `deepseek-r1:8b`).
    * Der System-Prompt zwingt das Modell, der Roadmap Schritt für Schritt zu folgen (`## Step 1: ...`, `## Step 2: ...`).
    * Da der Kontext (Memory + Plan) vollständig ist, ist das Ergebnis kohärenter als bei isolierten Schritten.

4. **Phase 3: Parsing & Validation**
    * Die Antwort wird via Regex in strukturierte Schritte zerlegt.
    * (Optional) `validate_step`: Einzelne Schritte können nachträglich vom CIM validiert werden.

---

## Wichtige Dateien

### 1. `sequential_thinking.py`

Die **Single-Source-of-Truth** für v3.0.

* Nutzt `FastMCP` für schlanke Server-Implementierung.
* Enthält `CIMClient` und `MemoryClient` für Kommunikation mit anderen Containern.
* Implementiert `think` als Haupt-Tool.

### 2. `sequential_mcp/` (Legacy/Resource)

* Enthält ältere oder alternative Implementierungen (`server.py` auf FastAPI-Basis).
* Ggf. noch für Typ-Definitionen oder Hilfsfunktionen genutzt, aber `sequential_thinking.py` ist der Entrypoint.

---

## MCP Tools

| Tool | Argumente | Beschreibung |
| :--- | :--- | :--- |
| **think** | `message`, `steps`, `mode`, `use_cim`, `use_memory` | Der Haupt-Modus. Kombiniert RAG + CIM + LLM zu einer Antwort. |
| **think_simple** | `message`, `steps` | Fallback ohne CIM/Memory. Reines "Chain of Thought". |
| **health** | - | Prüft Verbindung zu Ollama, CIM und Memory. |

## Konfiguration (ENV)

* `CIM_URL`: URL des CIM Servers (z.B. `http://cim-server:8086`).
* `MEMORY_URL`: URL des Memory Servers (z.B. `http://mcp-sql-memory:8081`).
* `OLLAMA_BASE`: URL der Ollama API.
* `OLLAMA_MODEL`: Zu nutzendes Modell (Standard: `deepseek-r1:8b`).
