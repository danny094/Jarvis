# Classifier Modul Dokumentation (`/classifier`)

Das Classifier-Modul ist die erste Verteidigungslinie und der "Router" für Informationen. Jede User-Nachricht wird hier analysiert, bevor sie den Core erreicht.

## Wichtige Dateien

-   **`classifier.py`**: Enthält die Logik für den API-Call an das Modell und das Parsing der Antwort.
-   **`system_*.txt`**: Diverse System-Prompts (werden vermutlich dynamisch geladen oder sind Legacy/Work-in-Progress). Der Hauptprompt ist in `classifier.py` als `SYSTEM_PROMPT` definiert (im aktuellen Stand).

## Funktionsweise

Die Funktion `classify_message(message, conversation_id)` führt folgende Schritte aus:

1.  **Prompt Construction**: Verbindet den User-Input mit einem strikten System-Prompt.
2.  **LLM Call**: Sendet die Anfrage an ein lokales Modell (konfiguriert als `qwen3:4b` oder ähnlich via `OLLAMA_BASE`).
    *   **Wichtig**: Nutzt `format: "json"` um valides JSON zu erzwingen.
3.  **Parsing & Validation**:
    *   Extrahiert JSON aus der Antwort.
    *   Validiert die Struktur (Fallback bei Fehlern: `irrelevant`).

## Das JSON Schema

Der Classifier liefert *immer* folgende Struktur:

```json
{
 "save": true/false,       // Soll diese Info gespeichert werden?
 "layer": "stm/mtm/ltm",   // Welcher Gedächtnis-Layer? (Short/Mid/Long Term)
 "type": "fact/task/...",  // Art der Info
 "key": "...",             // Optional: Schlüssel für Facts
 "value": "...",           // Optional: Wert für Facts
 "subject": "Danny",       // Auf wen bezieht es sich?
 "confidence": 0.0-1.0     // Unsicherheit
}
```

### Layer Definitionen
-   **STM (Short Term)**: Sofortige Relevanz, flüchtig (z.B. "Wie spät ist es?").
-   **MTM (Mid Term)**: Kontext für den Tag/die Session (z.B. "Ich bin müde").
-   **LTM (Long Term)**: Dauerhafte Fakten (z.B. "Ich wohne in Berlin").

## Wichtig zu beachten

> [!WARNING]
> **Modell-Abhängigkeit**: Der Classifier verlässt sich stark darauf, dass das Modell valides JSON produziert. Qwen und Llama 3 sind hierfür optimiert. Kleinere Modelle könnten scheitern.
> **Prompt-Engineering**: Der System-Prompt in `classifier.py` enthält viele Beispiele (Few-Shot), um das Verhalten zu steuern. Änderungen hier haben massive Auswirkungen auf die Speicher-Qualität.
