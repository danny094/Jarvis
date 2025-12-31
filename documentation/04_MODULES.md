# Modules Dokumentation (`/modules`)

Das `/modules` Verzeichnis enthält spezialisierte, in sich geschlossene Komponenten, die vom Core bei Bedarf aufgerufen werden.

## Meta Decision (`/modules/meta_decision`)

Dieses Modul ist ein spezialisierter Entscheider ("Meta Decision Layer").

### `decision.py`
-   **Funktion**: `run_decision_layer(payload)`
-   **Zweck**: Analysiert `user` Input + `memory` Kontext, um eine Entscheidung zu treffen, *bevor* komplexe Aktionen ausgeführt werden.
-   **Technik**: Nutzt einen eigenen Prompt (`decision_prompt.txt`) und ein kleines, schnelles Modell (z.B. `deepseek-r1:8b`), um Situationen zu bewerten.

## Validator (`/modules/validator`)

Der Validator ist für die Qualitätssicherung der Antworten zuständig.

### Architektur
Der Validator besteht aus zwei Teilen:
1.  **Client (`validator_client.py`)**: Ein Python-Client innerhalb des Assistant-Proxy.
2.  **Service (`validator-service`)**: Ein externer Microservice (lauffähig via Docker), der die eigentliche Prüfung durchführt.

### Validierungs-Arten
-   **Embedding Validator (`validate_embedding`)**: Prüft semantische Ähnlichkeit (Legacy).
-   **LLM Validator (`validate_instruction`)**: Prüft, ob die Antwort komplexe Instruktionen befolgt.
    *   Übergibt Parameter: `question`, `answer`, `instruction`, `rules`.
    *   Der externe Service nutzt ein LLM, um "Pass" oder "Fail" zu urteilen.
    *   Wird vom **Control Layer** genutzt, um Halluzinationen zu verhindern.

## Erweiterbarkeit

Neue Module können hier einfach hinzugefügt werden. Ein Modul sollte idealerweise:
1.  Einen klaren `client.py` oder Entry-Point haben.
2.  Unabhängig von Core-Internals sein (Loose Coupling).
3.  Eigene Konfiguration in sich kapseln.
