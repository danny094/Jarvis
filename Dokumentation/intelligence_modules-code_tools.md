# Causal Code Tools (`intelligence_modules/code_tools/`)

## Übersicht

Dieses Verzeichnis enthält die Werkzeuge, die TRION für **Deep Reasoning** und **Kausalanalyse** befähigen. Hier wird Philosophie und kognitive Wissenschaft in ausführbaren Python-Code übersetzt. Der Fokus liegt darauf, komplexe Probleme in berechenbare Graphen zu zerlegen und LLMs von mathematischer Unsicherheit zu befreien.

## Hauptkomponenten

### 1. `causal_controller.py`

Der Orchestrator des Kausal-Moduls.

- **Strategie**: Implementiert eine "Snowball Retrieval Strategy" über 3 Stufen:
    1. **Knowledge Scaffold**: Lädt kognitive Priors und Domain-Graphen.
    2. **Reasoning Plan**: Wählt eine Prozedur aus und prüft auf Anti-Patterns.
    3. **Execution Binding**: Bindet Tools und "Ability Injectors".

### 2. `context_builder.py`

Erstellt den Kausal-Graphen (`NetworkX` DiGraph).

- **Konzepte**:
  - **Nodes**: Exposure, Outcome, Confounder, Mediator, Collider.
  - **Edges**: Hypothesized Cause, Observed Correlation, Mechanism Step.
- **Features**: Erkennt automatisch Feedback-Loops und validiert DAG-Eigenschaften.

### 3. `causal_math_tools.py`

Eine Sammlung deterministischer Algorithmen. **LLMs dürfen nicht rechnen**, daher übernimmt dieses Modul:

- **Statistik**: Effektstärken ($d$), Konfidenzintervalle, Bayes-Updates.
- **Graph-Analyse**: Pfad-Suche, Bottleneck-Identifikation, Widerspruchs-Erkennung.
- **Hypothesen-Ranking**: Bewertet Erklärungsmodelle nach Bradford-Hill-Kriterien.

### 4. `prompt_engineer.py`

Übersetzt den internen Graphen zurück in natürliche Sprache für das LLM.

- Strukturiert den Prompt strikt nach Variablen, Constraints, Logic Gates und Reasoning Roadmap.
- Zwingt das LLM in ein kausales Korsett.

### 5. `visualizer.py` (`MermaidGenerator`)

Erzeugt visuelle Repräsentationen der Denkprozesse als Mermaid-Diagramme.

- Visualisiert Kausalketten, Logic Gates und Prozeduren farblich codiert.

### 6. `complex_scenarios.py`

Enthält komplexe Test-Szenarien ("Detective Investigation", "Medical Diagnosis") um die Fähigkeiten des Systems zu demonstrieren.

## Abhängigkeiten

- `networkx`: Für Graphen-Theorie.
- `pandas` / `numpy`: Für Datenhaltung und Berechnungen.
- `scipy`: Für statistische Tests.
