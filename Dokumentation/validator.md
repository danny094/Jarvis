# Validator Module (`modules/validator/`)

Dieses Modul ist der **Client** für den externen `validator-service`. Es ermöglicht anderen Komponenten, Antworten oder Ergebnisse gegen definierte Kriterien zu validieren.

## Architektur

Das Modul ist rein **client-seitig**. Die eigentliche Validierungs-Logik läuft im separaten `validator-service` Container (siehe dortiges Verzeichnis).

### Dateien

#### 1. `validator_client.py`

Stellt asynchrone Funktionen zur Verfügung, um den Service abzufragen.

* **`validate_instruction(question, answer, instruction, rules)`**:
  * Der moderne, **LLM-basierte Validator**.
  * Prüft, ob eine Antwort (`answer`) die Instruktionen (`instruction` + `rules`) für eine Frage (`question`) befolgt.
  * Rückgabe: `passed` (bool) und `reason`.
  * Nutzt den Endpoint: `POST /validate_llm`.

* **`validate_embedding(question, answer)`** *(Legacy)*:
  * Ein älterer Ansatz basierend auf Embedding-Ähnlichkeit.
  * Prüft, ob Frage und Antwort semantisch zueinander passen.
  * Nutzt den Endpoint: `POST /validate`.

#### 2. `config.py`

Konfiguration via Environment Variables.

* `VALIDATOR_URL`: URL des Services (Standard: `http://validator-service:8000`).
* `ENABLE_VALIDATION`: Master-Switch (Standard: `true`).
* `VALIDATION_THRESHOLD`: Schwellwert für Embedding-Checks (Standard: `0.70`).

---

## Nutzung

```python
from modules.validator.validator_client import validate_instruction

# Prüfen ob eine Antwort den Regeln folgt
result = await validate_instruction(
    question="Wie ist das Wetter?",
    answer="Ich darf keine Wetterdaten abrufen.",
    instruction="Beantworte Fragen.",
    rules="Verweigere Antworten zu Echtzeitdaten."
)

if result["passed"]:
    print("Validierung erfolgreich!")
else:
    print(f"Fehler: {result['reason']}")
```
