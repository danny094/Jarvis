# Local Graph Builders (`intelligence_modules/local_graph_builders/`)

## Übersicht

Die "Graph Builders" sind spezialisierte Konstrukteure für kausale Wissensgraphen. Je nach Art der Benutzeranfrage wird ein passender Builder ausgewählt, um das Problem in eine berechenbare Struktur zu übersetzen.

## Architektur

Alle Builder erben von `BaseGraphBuilder` und nutzen die gemeinsame RAG-Infrastruktur (`knowledge_rag`, `procedural_rag`) um Kontext zu laden. Der `GraphSelector` fungiert als Factory/Router.

### 1. `GraphSelector` (The Router)

Analysiert die Query auf Keywords und entscheidet, welcher Builder genutzt wird:

* "What if", "Imagine" → **Simulation**
* "Time", "Forecast" → **Temporal**
* "Strategy", "Optimize" → **Strategic**
* Komplexe Begriffe ("Bias", "Paradox") → **Heavy**
* Sonstiges → **Light**

### 2. Implementierungen

#### `LightGraphBuilder`

* **Ziel**: Schnelligkeit.
* **Strategie**: Single-Path Retrieval. Lädt nur den relevantesten Graphen und die passendste Prozedur.
* **Use-Case**: Einfache kausale Fragen ("Warum steigt die Inflation?").

#### `HeavyGraphBuilder`

* **Ziel**: Tiefe und Sicherheit.
* **Strategie**: Multi-Path Retrieval. Lädt bis zu 5 Priors und mehrere Prozeduren.
* **Feature**: **Anti-Pattern Logic Gates**. Fügt explizite "Gate Nodes" in den Graphen ein, die kognitive Verzerrungen (z.B. Simpson's Paradox) abfangen müssen.

#### `StrategicGraphBuilder`

* **Ziel**: Entscheidungsfindung.
* **Strategie**: Influence Diagrams.
* **Nodes**: Fügt `DECISION_ACTION` (Intervention) und `UTILITY_GOAL` (Zielvariable) hinzu.
* **Use-Case**: "Was ist die beste Strategie um Churn zu reduzieren?"

#### `TemporalGraphBuilder`

* **Ziel**: Zeitreihen-Analyse.
* **Strategie**: Time-Lag Awareness.
* **Nodes**: Repräsentiert Variablen oft mit Zeitversatz (t, t-1). Nutzt `EdgeType.TEMPORAL_PRECEDENCE`.

#### `SimulationGraphBuilder`

* **Ziel**: Counterfactual Reasoning ("Was wäre wenn?").
* **Strategie**: Branching Worlds.
* **Nodes**: Erstellt parallele Welt-Zustände:
  * `WORLD_BASELINE` (Status Quo)
  * `WORLD_COUNTERFACTUAL` (Intervention)
* **Use-Case**: Szenario-Planung und Sensitivitätsanalyse.

## Abhängigkeiten

* `code_tools.context_builder`: Zur Erstellung der `CausalNode` und `CausalEdge` Objekte.
* RAG-CSVs: `cognitive_priors_v2.csv`, `domain_graphs.csv`, `causal_reasoning_procedures_v2.csv`.
