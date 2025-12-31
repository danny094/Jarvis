# Projekt Überblick & Architektur

## Einleitung
Dieses Dokument bietet eine umfassende Übersicht über das "Assistant Proxy" Framework, das in Zusammenarbeit mit Claude entwickelt wird. Das System ist eine hochmoderne KI-Architektur, die auf autonomen Agenten, Memory-Graph-Strukturen und strikter Validierung basiert.

## High-Level Architektur

Das System folgt einer strikten Trennung der Verantwortlichkeiten (Separation of Concerns). Die Hauptkomponenten sind:

1.  **Classifier (`/classifier`)**:
    *   Der "Pförtner" des Systems.
    *   Analysiert jede eingehende Nachricht VOR der eigentlichen Verarbeitung.
    *   Entscheidet, ob Informationen gespeichert werden (`stm`, `mtm`, `ltm`) und um welchen Typ (`fact`, `task`, `emotion`) es sich handelt.
    *   Gibt strukturiertes JSON zurück.

2.  **Core Bridge (`/core`)**:
    *   Das Herzstück und der Orchestrator.
    *   Verbindet die drei kognitiven Layer:
        1.  **Thinking Layer**: Plant und analysiert tiefgehend (oft mit DeepSeek).
        2.  **Control Layer**: Überprüft die Pläne auf Sicherheit, Logik und Konformität.
        3.  **Output Layer**: Formuliert die finale Antwort für den Nutzer.
    *   Verwaltet das Memory-Retrieval (User- & System-Wissen).

3.  **MCP Hub (`/mcp`)**:
    *   **Model Context Protocol** Implementierung.
    *   Verwaltet "Tools" als MCP-Server.
    *   Erlaubt das dynamische Einbinden von Funktionen (z.B. Memory-Datenbank, Websuche, File-Access).
    *   Abstrahiert die Kommunikation (Transport Layer) zu externen Diensten.

4.  **Modules (`/modules`)**:
    *   Spezialisierte, austauschbare Einheiten.
    *   **Meta Decision**: Entscheidungskomponente (z.B. "Brauche ich ein Tool?").
    *   **Validator**: Validiert Antworten gegen Instruktionen und Fakten.

## Datenfluss (vereinfacht)

1.  **User Request** trifft ein.
2.  **Classifier** analysiert: "Speichern? Was ist das?" -> JSON.
3.  **Core Bridge** übernimmt:
    *   Lädt relevanten Kontext (Memory + System-Wissen).
    *   **Thinking Layer**: "Was muss ich tun?" -> Plan.
    *   **Control Layer**: "Ist der Plan sicher?" -> Go/No-Go.
    *   **Output Layer**: Generiert Antwort.
4.  **MCP Hub** wird bei Bedarf aufgerufen (z.B. "Speichere Fakt X").

## Verzeichnisstruktur

```text
/assistant-proxy
├── classifier/       # Eingangs-Analyse
├── core/             # Hauptlogik & Layer (Thinking/Control/Output)
├── mcp/              # Tool-Integration & Protocol
├── modules/          # Spezialmodule (Decision, Validator)
└── utils/            # Hilfsfunktionen
```
