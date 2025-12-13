# 📦 Deprecated Code

Diese Dateien wurden am **11.12.2024** hierher verschoben, da sie nicht mehr aktiv genutzt werden.

## Warum?

Die **LobeChat-Adapter-Architektur** (`adapters/lobechat/`) ist jetzt der Haupteinstiegspunkt.  
Der alte `app.py`-basierte Server wird nicht mehr verwendet.

## Was ist hier?

| Datei/Ordner | Ursprung | Warum deprecated |
|--------------|----------|------------------|
| `app.py` | `/app.py` | Alter FastAPI-Server, ersetzt durch LobeChat-Adapter |
| `main.py` | `/main.py` | Startpunkt für app.py |
| `Dockerfile.old` | `/Dockerfile` | Altes Dockerfile für app.py |
| `ollama_chat.py` | `/ollama/chat.py` | Alte Chat-Pipeline, CoreBridge ersetzt das |
| `ollama_generate.py` | `/ollama/generate.py` | Alte Generate-Pipeline |
| `meta_decision/` | `/modules/meta_decision/` | ThinkingLayer ersetzt das |
| `classifier/` | `/classifier/` | ThinkingLayer ersetzt das |
| `validator/` | `/modules/validator/` | War Client für Validator-Service |

## Kann ich das löschen?

Ja, wenn alles stabil läuft, kann dieser Ordner gelöscht werden.

## Aktive Architektur

```
adapters/lobechat/main.py      ← Haupteinstiegspunkt (Port 8100)
    ↓
core/bridge.py                 ← CoreBridge orchestriert:
    ↓
core/layers/thinking.py        ← Layer 1: Intent-Analyse
core/layers/control.py         ← Layer 2: Verifikation
core/layers/output.py          ← Layer 3: Antwort-Generierung
```
