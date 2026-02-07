# Meta Decision Module (`modules/meta_decision/`)

Der **Meta-Decision Layer** ist eine vorgeschaltete Entscheidungsinstanz, die **vor** dem eigentlichen Reasoning-Prozess (Sequential Thinking) oder der Tool-Execution läuft.

Er analysiert den User-Input und entscheidet strategisch über:

1. **Sicherheit (`allow`)**: Darf die Anfrage überhaupt beantwortet werden?
2. **Memory-Nutzung (`use_memory`)**: Ist der Kontext aus dem Langzeitgedächtnis relevant?
3. **Memory-Updates (`update_memory`)**: Enthält der Input neue Fakten über den User, die gespeichert werden sollen?
4. **Rewrite (`rewrite`)**: Muss die Query umgeschrieben werden, um präziser oder sicherer zu sein?
5. **Risiko-Einschätzung (`hallucination_risk`)**: Wie wahrscheinlich ist eine Halluzination bei diesem Thema?

## Architektur

Das Modul ist bewusst **leichtgwiegt** gehalten und nutzt ein spezialisiertes Prompting mit einem schnellen Modell (Standard: `deepseek-r1:8b`).

### Dateien

#### 1. `decision.py`

Die Kern-Logik.

* Lädt den Prompt aus `decision_prompt.txt`.
* Ersetzt Platzhalter (`<<<USER>>>`, `<<<MEMORY>>>`).
* Ruft `utils.ollama.query_model` auf.
* Extrahiert und parst das JSON aus der Antwort (inklusiv Error-Handling).

#### 2. `decision_client.py`

Der Python-Client für die interne Nutzung.

* Funktion `ask_meta_decision(user_text)`.
* Wrapper um `decision.py` mit Logging und Error-Fallback.
* Fallbacks: Wenn das LLM versagt, wird standardmäßig "Memory aus, kein Rewrite" zurückgegeben (Fail-Safe).

#### 3. `decision_router.py`

Ein FastAPI Router (`APIRouter`).

* Stellt den Endpoint `POST /decision` bereit.
* Erlaubt externen Services (z.B. anderen Containern), eine Meta-Entscheidung anzufordern.

#### 4. `decision_prompt.txt`

Der System-Prompt für das LLM.

* Definiert strikte JSON-Output-Regeln.
* Untersagt "Thinking" im Output (Chain-of-Thought nur intern erlaubt).
* Definiert Kriterien für `hallucination_risk` und `update_memory`.

---

## Output Format

Der Layer liefert immer ein JSON-Objekt in dieser Struktur:

```json
{
  "allow": true,
  "use_memory": false,
  "hallucination_risk": "low",
  "rewrite": "",
  "update_memory": null
}
```

Oder bei einem Memory-Update:

```json
{
  "allow": true,
  "use_memory": true,
  "hallucination_risk": "low",
  "rewrite": "",
  "update_memory": {
      "key": "user_preference_editor",
      "value": "vim"
  }
}
```

## Nutzung

```python
from modules.meta_decision.decision_client import ask_meta_decision

# User Input
query = "Mein Name ist Dennis und ich nutze gerne Vim."

# Entscheidung abholen
decision = await ask_meta_decision(query)

if decision.get("update_memory"):
    # ... speichere Fakten ...
    pass

if decision.get("use_memory"):
    # ... lade Kontext ...
    pass
```
