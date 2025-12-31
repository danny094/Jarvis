# Core Modul Dokumentation (`/core`)

Das `/core` Modul ist das zentrale Nervensystem des Frameworks. Hier laufen alle Fäden zusammen: State-Management, Layer-Orchestrierung und Memory-Zugriff.

## Wichtige Dateien

-   **`bridge.py` (`CoreBridge`)**: Die Hauptklasse. Sie steuert den Ablauf `Thinking -> Control -> Output`.
-   **`models.py`**: Definiert die internen Datenstrukturen (`CoreChatRequest`, `CoreChatResponse`, `Message`).
-   **`layers/`**: Beinhaltet die Logik der drei kognitiven Schichten.

## Die Core Bridge (`bridge.py`)

Die `CoreBridge` ist als Singleton implementiert (`get_bridge()`) und orchestriert die Anfrageverarbeitung.

### Hauptablauf (Pipeline)

1.  **Initialisierung**: `CoreBridge` wird instanziiert, lädt Layer.
2.  **Memory Retrieval (`_search_memory_multi_context`)**:
    *   Sucht parallel in zwei Kontexten:
        *   `user` (aktuelle Konversation, Fakten über Danny).
        *   `system` (Instruktionen, Tool-Dokumentation).
    *   Nutzt Fakten-Suche, Graph-Suche und Semantische Suche.
3.  **Layer-Exekution**:
    *   Die Bridge ruft nacheinander die Layer auf (Logik in `layers/`).
    *   Daten werden über `CoreChatRequest` und `CoreChatResponse` Objekte weitergereicht.

## Datenmodelle (`models.py`)

Zentralisierung der Datenstrukturen ist kritisch für die Stabilität.

-   **`Message`**: Standarisiertes Format für Chat-Nachrichten (`role`, `content`).
-   **`CoreChatRequest`**:
    *   Enthält alle Messages.
    *   `conversation_id`: Trennung von Kontexten.
    *   Metadaten vom Adapter.
-   **`CoreChatResponse`**:
    *   Antwort-Text.
    *   `done_reason`: Warum wurde gestoppt?
    *   `classifier_result`: Was hat der Classifier am Anfang gesagt?

## Speicher-Strategie (Memory)

Das Core-Modul unterscheidet strikt zwischen:
-   **User Memory**: Fakten über den Nutzer (Alter, Vorlieben, Aufgaben).
-   **System Memory**: "Wissen" des Assistenten über sich selbst und seine Tools.

Die Methoden `_search_memory_multi_context` und `get_system_knowledge` stellen sicher, dass der Assistent Zugriff auf *beide* Wissenspools hat, ohne sie zu vermischen.

## Wichtig zu beachten

> [!IMPORTANT]
> **Async Flow**: Die gesamte Bridge arbeitet asynchron. Blockierende Aufrufe sollten vermieden werden.
> **Singleton**: `get_bridge()` garantiert, dass der State global konsistent bleibt.
> **System Context**: Die `conversation_id="system"` ist reserviert für Tool-Definitionen und Meta-Wissen.
