# classifier/classifier.py

import json
import requests
from config import OLLAMA_BASE
from utils.logger import log_info, log_error

CLASSIFIER_MODEL = "qwen3:4b"


SYSTEM_PROMPT = SYSTEM_PROMPT = """
Du bist ein strikter JSON-Klassifizierer für ein KI-Memory-System.
Du MUSST immer und ausschließlich gültiges JSON zurückgeben.
KEIN Text davor oder danach. KEINE Erklärungen. KEINE Emojis.

=====================================
AUFGABE
=====================================
Analysiere die User-Nachricht und entscheide folgende Felder:

{
 "save": true/false,
 "layer": "stm" | "mtm" | "ltm",
 "type": "fact" | "identity" | "preference" | "task" | "emotion" | "fact_query" | "irrelevant",
 "key": "",
 "value": "",
 "subject": "Danny",
 "confidence": 0.0 - 1.0
}

Erklärung der Felder:
- save: Ob gespeichert werden soll.
- layer:
    - stm = Kurzzeitgedächtnis
    - mtm = mittelfristige Infos
    - ltm = langfristige Fakten
- type: Typ der Information
- key/value: Strukturierte Fakten, falls vorhanden
- subject: IMMER "Danny" wenn es um den Benutzer geht
- confidence: 0.0 bis 1.0

=====================================
REGELN
=====================================

1) **Fakten über Danny → ltm**
Beispiele:
- "Ich bin 31 Jahre alt." → key="age"
- "Mein Geburtstag ist am 19. November." → key="birthday"
- "Ich wohne in Berlin." → key="location"
- "Mein Name ist Danny." → key="name"

Immer:
save = true  
layer = "ltm"  
type  = "fact"  
confidence ≥ 0.95  

2) **Fakt-Abfragen → fact_query**
Erkennen, wenn der User eine gespeicherte Information zurückhaben will.

Beispiele:
- "Wie alt bin ich noch mal?"
- "Wann habe ich Geburtstag?"
- "Wo wohne ich noch mal?"
- "Kannst du mir mein Alter sagen?"

Dann:
type = "fact_query"  
key = z.B. "age", "birthday", "location"  
save = false  
layer = "stm"

3) **Temporäre Gefühle / Zustände → mtm**
Beispiele:
- "Ich bin müde."
- "Mir geht’s schlecht."
- "Ich habe Kopfschmerzen."

Dann:
type = "emotion"  
layer = "mtm"  
save = true  

4) **Aufgaben / To-Dos**
Beispiele:
- "Erinnere mich morgen ans Einkaufen."
- "Ich muss später noch meine Mutter anrufen."

Dann:
type = "task"  
layer = "stm"  
save = true  

5) **Vorlieben**
Beispiele:
- "Ich mag Vanilleeis."
- "Meine Lieblingsfarbe ist blau."

Dann:
type = "preference"  
layer = "ltm"  
save = true  

6) **Smalltalk / irrelevante Chatnachrichten**
Beispiele:
- "Wie geht's?"
- "Haha lol"
- "Okay!"

Dann:
type = "irrelevant"  
save = false  
layer = "stm"  
confidence < 0.3  

=====================================
BEISPIELE (Sehr wichtig!)
=====================================

Eingabe:
"Ich bin 31 Jahre alt."
Ausgabe:
{"save": true, "layer": "ltm", "type": "fact", "key": "age", "value": "31", "subject": "Danny", "confidence": 1.0}

Eingabe:
"Wie alt bin ich noch mal?"
Ausgabe:
{"save": false, "layer": "stm", "type": "fact_query", "key": "age", "value": "", "subject": "Danny", "confidence": 1.0}

Eingabe:
"Ich bin gerade total müde."
Ausgabe:
{"save": true, "layer": "mtm", "type": "emotion", "key": "", "value": "", "subject": "Danny", "confidence": 1.0}

Eingabe:
"Okay danke dir!"
Ausgabe:
{"save": false, "layer": "stm", "type": "irrelevant", "key": "", "value": "", "subject": "Danny", "confidence": 0.1}

=====================================
WICHTIG:
- IMMER gültiges JSON.
- KEINE Kommentare.
- KEIN Text außer dem JSON.
- Selbst wenn du unsicher bist: gültiges JSON zurückgeben.
"""


def classify_message(message: str, conversation_id: str):
    """
    Ruft das Klassifizierermodell über /api/generate auf.
    Erwartet reines JSON in 'response'.
    """

    if not message.strip():
        return {
            "save": False,
            "layer": "stm",
            "type": "irrelevant",
            "confidence": 0.0
        }

    payload = {
        "model": CLASSIFIER_MODEL,
        "prompt": f"{SYSTEM_PROMPT}\n\nUSER:\n{message}",
        "format": "json",        # <<< WICHTIG FÜR LLAMA!
        "stream": False
    }

    try:
        r = requests.post(
            f"{OLLAMA_BASE}/api/generate",
            json=payload,
            timeout=20
        )
        r.raise_for_status()

        data = r.json()
        content = data.get("response", "").strip()

        # Qwen3 nutzt manchmal "thinking" statt "response"
        if not content and data.get("thinking"):
            content = data.get("thinking", "").strip()
            log_info(f"[Classifier] Using 'thinking' field instead of 'response'")

        if not content:
            log_error(f"[Classifier] Leere Antwort → {data}")
            return {"save": False, "layer": "stm", "type": "irrelevant", "confidence": 0.0}

        try:
            result = json.loads(content)
        except Exception:
            log_error(f"[Classifier] Ungültiges JSON vom Modell: {content}")
            return {"save": False, "layer": "stm", "type": "irrelevant", "confidence": 0.0}

        if not isinstance(result, dict):
            log_error(f"[Classifier] Kein dict: {result}")
            return {"save": False, "layer": "stm", "type": "irrelevant", "confidence": 0.0}

        log_info(f"[Classifier] → save={result.get('save')} layer={result.get('layer')} type={result.get('type')}")
        return result

    except Exception as e:
        log_error(f"[Classifier] Fehler: {e}")
        return {"save": False, "layer": "stm", "type": "irrelevant", "confidence": 0.0}