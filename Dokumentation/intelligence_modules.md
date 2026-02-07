# Intelligence Modules (`intelligence_modules/`)

## Übersicht

Dieses Verzeichnis enthält spezialisierte Module für logisches Denken, Code-Generierung und Kausalanalyse ("Causal Intelligence"). Diese Module erweitern die kognitiven Fähigkeiten von TRION über das reine LLM-Reasoning hinaus.

## Module (Übersicht)

### Core

* **`cim.py` (Causal Intelligence Module)**:
  * Der CLI-Einstiegspunkt für komplexe Kausalanalyse.
  * Nutzt `GraphSelector` um den richtigen "Graphen-Builder" für eine Anfrage auszuwählen.
  * Erstellt Audit-Logs (`tracing`) aller Denkprozesse.
  * Kann Prompts generieren (`CausalPromptEngineer`) oder Mermaid-Diagramme (`MermaidGenerator`).

### Sub-Module

* **`cim_policy/`**: Policy Engine für kontrollierte Autonomie (siehe [README](./cim_policy/README.md)). Entscheidet, wann Skills automatisch erstellt oder ausgeführt werden dürfen.
* **`code_tools/`**: Werkzeuge zur Code-Analyse und -Generierung (Visualizer, Prompt Engineer).
* **`local_graph_builders/`**: Logik zum Aufbau von kausalen Wissensgraphen für verschiedene Szenarien.
* **`executable_rag` / `knowledge_rag` / `procedural_rag`**: Spezialisierte RAG-Implementierungen.
* **`cloud_n8n_*`**: Integrationen für n8n Workflows.

## Verwendung

Die meisten dieser Module werden vom Core-Orchestrator oder spezifischen Tools aufgerufen. `cim.py` kann auch standalone via CLI genutzt werden:

```bash
python3 cim.py "Analysiere den Fehler im Login-Prozess" --visual
```
