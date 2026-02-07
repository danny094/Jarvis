# SQL Memory Server (`sql-memory/`)

Der **SQL Memory Server** ist das zentrale Langzeitgedächtnis von TRION. Er ist weit mehr als eine einfache Datenbank – er ist ein **hybrides Speichersystem**, das relationale Daten (SQL), semantische Embeddings (Vector) und Wissensgraphen (Graph) vereint.

## Architektur

Der Server basiert auf **FastMCP** und läuft standardmäßig auf **Port 8081**.

### Speicher-Ebenen (Layers)

Das Gedächtnis ist in drei zeitliche Ebenen unterteilt (inspiriert vom menschlichen Gehirn):

1. **STM (Short-Term Memory)**: Flüchtige, aktuelle Informationen.
2. **MTM (Mid-Term Memory)**: Konsolidierte Informationen, die über mehrere Tage relevant sind.
3. **LTM (Long-Term Memory)**: Dauerhaftes Wissen und Fakten.

### Komponenten

#### 1. Core (`memory_mcp/`)

* **`server.py`**: Entry-Point. Startet den FastMCP Server, führt DB-Migrationen durch und registriert Tools.
* **`database.py`**: Data Access Layer (DAL) für SQLite. Verwaltet Tabellen für:
  * `memory`: Der eigentliche Chat/Text-Speicher.
  * `facts`: Strukturierte Key-Value Fakten.
  * `skill_metrics`: Metriken zur Skill-Ausführung (Erfolg/Fehler/Zeit).
  * `workspace_entries`: Session-Daten für langlaufende Tasks.
* **`tools.py`**: Implementiert die MCP-Tools (siehe unten).

#### 2. AI Maintenance (`maintenance_ai.py`)

Ein autonomer "Hausmeister"-Prozess, der:

* **STM $\to$ LTM Promotion**: Nutzt ein LLM (z.B. Qwen), um wichtige Kurzzeit-Erinnerungen zu identifizieren und ins Langzeitgedächtnis zu verschieben.
* **Dual Validation**: Kann einen zweiten "Critic"-LLM nutzen, um Entscheidungen zu verifizieren (4-Augen-Prinzip).
* **Graph Optimization**: Findet und bereinigt verwaiste Knoten.
* **Deduplication**: Entfernt doppelte Einträge.

#### 3. Vector & Graph (`vector_store.py`, `graph/`)

* **Vector Store**: Speichert Embeddings für semantische Suche ("Finde etwas, das so ähnlich klingt wie...").
* **Graph Store**: Speichert Beziehungen zwischen Fakten (Subject $\xrightarrow{predicate}$ Object). Ermöglicht Multi-Hop Reasoning.

---

## Wichtige Tools

### Speichern & Lesen

* `memory_save(content, role, tags)`: Speichert Text (automatisch STM).
* `memory_search(query)`: Klassische Volltextsuche (FTS5).
* `memory_semantic_search(query)`: Suche nach Bedeutung (Vektor).
* `memory_recent(limit)`: Die letzten N Einträge abrufen.

### Fakten & Wissen

* `memory_fact_save(subject, key, value)`: Speichert einen strukturierten Fakt (z.B. "User liebt Pizza").
* `memory_graph_search(query, depth)`: Durchwandert den Wissensgraphen, um Zusammenhänge zu finden.
* `memory_graph_neighbors(node_id)`: Zeigt benachbarte Knoten im Graphen.

### Maintenance

* `maintenance_run(model)`: Stößt den AI-Cleanup-Prozess manuell an.
* `memory_delete_bulk(ids)`: Löscht mehrere Einträge (für Cleanup).
* `graph_merge_nodes(ids)`: Führt Duplikate im Graphen zusammen.

---

## Datenbank-Schema

Die SQLite-Datenbank (`data/memory.db`) enthält folgende Haupttabellen:

| Tabelle | Beschreibung |
| :--- | :--- |
| `memory` | Hauptspeicher (Rohtext, Rolle, Layer) |
| `facts` | Strukturierte Fakten (Subject, Key, Value) |
| `memory_fts` | Virtuelle Tabelle für schnelle Volltextsuche |
| `graph_nodes` | Knoten des Wissensgraphen |
| `graph_edges` | Kanten (Beziehungen) des Graphen |
| `workspace_entries` | Temporäre Daten für aktive Arbeits-Sessions |
