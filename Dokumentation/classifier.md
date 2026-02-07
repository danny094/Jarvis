# Classifier Module (`classifier/`)

## Übersicht

Das `classifier` Modul ist für die **Klassifizierung von Informationen** zuständig. Es analysiert User-Nachrichten und entscheidet, ob und wo diese im Gedächtnis gespeichert werden sollen.

## Hauptkomponenten

### 1. `classifier.py`

Dies ist das Kern-Modul.

- **Funktion**: Ruft ein lokales LLM (Standard: `qwen3:4b`) auf, um den Input zu klassifizieren.
- **Output**: Ein JSON-Objekt mit:
  - `save`: Soll gespeichert werden? (`true`/`false`)
  - `layer`: Ziel-Layer (`stm` = Short, `mtm` = Medium, `ltm` = Long Term Memory).
  - `type`: Art der Info (`fact`, `preference`, `task`, `emotion`, `fact_query`, `irrelevant`).
  - `key` / `value`: Strukturierte Daten (wenn anwendbar).
  - `confidence`: Sicherheitsscore (0.0 - 1.0).

### 2. `prompts.py`

Enthält alternative oder simplere Prompts für Klassifizierungsaufgaben. (Scheint legacy oder sekundär zu sein, da `classifier.py` seinen eigenen `SYSTEM_PROMPT` definiert).

### 3. `system-prompts/` (Verzeichnis)

Eine Sammlung von modularen System-Prompts als `.txt` Dateien. Diese dienen als Bausteine für verschiedene Assistant-Personas oder Modi.

- `system_core.txt`: Kern-Instruktionen.
- `system_memory.txt`: Regeln zum Umgang mit Gedächtnis.
- `system_safety.txt`: Sicherheitsregeln.
- `prompt_system.txt`: Ein kombinierter oder komplexerer Prompt.
- ... und weitere spezialisierte Prompts (`persona`, `meta_guard`, `style_de`).

## Funktionsweise der Klassifizierung

Der Classifier unterscheidet strikt zwischen:

1. **Fakten (`ltm`)**: Dauerhafte Wahrheiten ("Ich heiße Danny").
2. **Tasks/Emotionen (`stm`/`mtm`)**: Temporäre Zustände ("Ich bin müde", "Erinnere mich morgen").
3. **Abfragen (`fact_query`)**: Wenn der User etwas wissen will, was er schon mal gesagt hat ("Wie alt bin ich?").
4. **Irrelevant**: Smalltalk oder nicht speicherwürdige Interaktionen.

## Wichtige Imports

- `requests`: Für synchrone HTTP-Calls zur Ollama API.
- `json`: Zum Parsen der LLM-Antwort.
- `config`: Lädt Basis-Konfigurationen (`OLLAMA_BASE`).
