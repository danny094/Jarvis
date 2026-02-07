# CIM Server (`mcp-servers/cim-server/`)

Der **CIM Server** (Causal Intelligence Module) ist das logische Gehirn von TRION. Er basiert auf **Frank's Causal Design** und stellt die "Reasoning Roadmaps" bereit, die vom `sequential-thinking`-Server ausgeführt werden.

## Architektur

Der Server ist ein **FastMCP-Wrapper** um die lokalen Python-Module in `intelligence_modules`. Er läuft als eigenständiger Container und mountet den Code als Volume.

### Kern-Komponenten

1. **Graph Selector**: Entscheidet automatisch basierend auf der Query-Komplexität, welcher Builder genutzt wird.
2. **Graph Builders** (in `intelligence_modules/local_graph_builders`):
    * `LightGraphBuilder`: Schnell, für einfache Checks.
    * `HeavyGraphBuilder`: Gründlich, injiziert Logic-Gates und Validierungen.
    * `StrategicGraphBuilder`: Für Entscheidungsbäume und Utility-Optimierung.
    * `TemporalGraphBuilder`: Für Zeitreihen und Historien.
    * `SimulationGraphBuilder`: Für "Was-wäre-wenn" Szenarien (Counterfactuals).
3. **Prompt Engineer**: Wandelt den abstrakten Causal-Graph in einen textuellen System-Prompt ("Reasoning Roadmap") um.
4. **Audit Log**: Speichert jeden Trace als JSON in `logs/causal_traces`.

---

## Wichtige Dateien

### `cim_server.py`

Der Entrypoint.

* Initiiert `FastMCP` auf Port **8086**.
* Lädt Anti-Patterns aus `procedural_rag/anti_patterns.csv`.
* Implementiert die Tools:
  * `analyze`: Der Haupt-Endpoint für Sequential Thinking.
  * `validate_before` / `validate_after`: Sicherheits-Checks.
  * `correct_course`: "Self-Correction" bei Fehlern.

---

## MCP Tools

| Tool | Argumente | Beschreibung |
| :--- | :--- | :--- |
| **analyze** | `query`, `mode` | Erstellt einen kausalen Graphen und liefert die "Roadmap" für das LLM. |
| **validate_before** | `step_description`, `context` | Prüft einen geplanten Schritt auf Logikfehler (Pre-Mortem). |
| **validate_after** | `step_result`, `expected` | Prüft ein Ergebnis auf Halluzinationen oder Inkonsistenzen (Post-Mortem). |
| **correct_course** | `current_plan`, `violations` | Generiert einen korrigierten Plan, wenn Validierungen fehlschlagen. |
| **get_modes** | - | Listet alle verfügbaren Grafik-Builder-Modi. |
| **health** | - | Healthcheck. |

## Konfiguration (ENV)

* `CIM_ROOT`: Pfad zu den Intelligence Modules (Standard: `/app/intelligence_modules`).
* `PORT`: Port des Servers (Standard: `8086`).

## Abhängigkeiten

* `fastmcp`: Für das MCP Protokoll.
* `networkx`: Für die Graphen-Berechnung.
* `pandas`/`numpy`: Für numerische Berechnungen in den Buildern.
