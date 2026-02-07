# Knowledge Graph (`sql-memory/graph/`)

Das Model `graph` implementiert eine **Graph-Datenbank direkt auf SQLite**. Es ermöglicht TRION, Beziehungen zwischen Informationen zu speichern und abzufragen, was für komplexes Reasoning unerlässlich ist.

## Architektur

Der Graph besteht aus **Nodes** (Knoten) und **Edges** (Kanten), die in zwei relationalen Tabellen gespeichert werden. Dies vermeidet die Notwendigkeit einer separaten Graph-Datenbank wie Neo4j.

### Tabellen-Struktur

#### 1. `graph_nodes`

Repräsentiert Entitäten, Fakten oder Nachrichtenteile.

* **`id`**: Eindeutige ID.
* **`source_type`**: Art der Quelle (z.B. "fact", "message", "file").
* **`content`**: Der Textinhalt.
* **`embedding`**: Vektor-Embedding (als JSON/BLOB) für semantische Ähnlichkeit.
* **`confidence`**: Vertrauenswürdigkeit (0.5 = Standard, 0.9 = von Mensch bestätigt/promoted).

#### 2. `graph_edges`

Repräsentiert die Verbindungen.

* **`src_node_id`** $\to$ **`dst_node_id`**: Gerichtet.
* **`edge_type`**: Art der Beziehung (siehe unten).
* **`weight`**: Stärke der Verbindung (0.0 - 1.0).

---

## Komponenten

### `graph_store.py` (`GraphStore`)

Die Low-Level API für Datenbank-Operationen.

* **CRUD**: `add_node`, `add_edge`, `get_node`, `delete_node`.
* **Traversal**:
  * `get_neighbors(node_id)`: Findet direkt verbundene Knoten.
  * **`graph_walk(start_ids, depth)`**: Führt eine Breitensuche (BFS) durch, um Kontexte zu finden, die nicht direkt benachbart sind (Multi-Hop Retrieval).

### `graph_builder.py` (`GraphBuilder`)

Die "Intelligenz" beim Speichern. Wenn ein neuer Knoten (z.B. ein neuer Fakt) hinzugefügt wird, versucht dieser Builder automatisch, sinnvolle Verbindungen zu erstellen:

1. **Temporal Edges** (`temporal`):
    * Verbindet den neuen Knoten mit dem *letzten* Knoten derselben Konversation.
    * Ziel: Chronologie der Gedanken erhalten ("Das habe ich *danach* gesagt").

2. **Semantic Edges** (`semantic`):
    * Vergleicht das Embedding des neuen Knotens mit bestehenden Knoten.
    * Bei hoher Ähnlichkeit ($\ge 0.70$) wird eine Kante erstellt.
    * Ziel: Inhalte verknüpfen, die thematisch gleich sind, auch wenn sie zeitlich weit auseinander liegen.

3. **Co-occurrence Edges** (`cooccur`):
    * Verbindet Knoten, die dieselben Schlüsselwörter (`related_keys`) teilen.
    * Ziel: Fakten gruppieren, die zum selben Thema gehören (z.B. alle Fakten über "Projekt X").

---

## Nutzung im System

Der Graph wird primär über den `memory_mcp` Server (Tool: `memory_graph_search`) genutzt.

**Szenario**:
Der User fragt: *"Was weißt du über meine Server-Probleme?"*

1. Die Vektor-Suche findet einen aktuellen Eintrag: *"Server ist down wegen SSH Key"*.
2. Der `graph_walk` startet bei diesem Knoten.
3. Er findet über eine **Temporal Edge** einen Eintrag von vor 3 Tagen: *"Habe den SSH Key geändert"*.
4. TRION kann nun schlussfolgern: *Der Key-Wechsel ist die Ursache.* (Ohne Graph wäre der alte Eintrag im Rauschen untergegangen).
