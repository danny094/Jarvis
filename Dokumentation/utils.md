# TRION Utils (`utils/`)

Dieses Verzeichnis enthält wiederverwendbare Hilfsmodule, die von verschiedenen TRION-Komponenten genutzt werden. Sie bilden das **Fundament für Text-Processing, State-Management und LLM-Interaktion**.

## Wichtige Module

### 1. `chunker.py` (Text-Splitting)

Ein fortgeschrittener, semantischer Chunker für RAG und Dokumentenverarbeitung.

* **Funktionen**: `Chunker.chunk()`, `count_tokens()`, `analyze_document_structure()`
* **Features**:
  * **Semantische Grenzen**: Trennt an Paragraphen, Überschriften, Sätzen.
  * **Code-Protection**: Erkennt Markdown-Codeblöcke und versucht, diese *nicht* zu zerschneiden.
  * **Token-Aware**: Nutzt `tiktoken` (wenn verfügbar) oder eine Heuristik für exakte Limits.
  * **Overlap**: Behält Kontext zwischen Chunks bei.

### 2. `workspace.py` (Session & State)

Ein Datei-basierter Session-Manager für langlaufende, gechunkte Prozesses (z.B. "Lies dieses Buch").

* **Pfad**: `/tmp/trion/jarvis/workspace/{conversation_id}/`
* **Struktur**:
  * `meta.json`: Status, Token-Count, Fortschritt.
  * `input.txt`: Der originale Input-Text.
  * `chunks/`: Verzeichnis mit einzelnen JSON-Files pro Chunk (Status, Ergebnis).
* **Features**: Locking, Cleanup (TTL), Status-Tracking (Pending/Done/Failed).

### 3. `json_parser.py` (Robustheit)

Ein "Last Resort" Parser für LLM-Antworten.

* **Problem**: LLMs liefern oft "fast" JSON (Markdown-Wrapper, Kommentare, Trailing Commas).
* **Strategien**:
    1. Standard `json.loads`.
    2. Extraktion zwischen den ersten `{` und letzten `}`.
    3. Regex für Markdown-Codeblöcke (` ```json ... ``` `).
    4. **Auto-Repair**: Entfernt Trailing Commas, fixt Quotes.
    5. **Regex-Fallback**: Versucht Key-Values direkt aus dem Text zu kratzen.

### 4. `settings.py` (Konfiguration)

Ein einfacher Key-Value Store für persistente Einstellungen.

* Speichert Configs in `config/settings.json`.

### 5. `logger.py` & `ollama.py`

* `logger.py`: Standardisiertes Logging mit Zeitstempel und Levels.
* `ollama.py`: Ein einfacher `requests`-Wrapper für die Ollama API (Legacy/Basic Support).

---

## Verwendung (Beispiele)

### Chunker

```python
from utils.chunker import Chunker

chunker = Chunker(max_tokens=2000, overlap_tokens=200)
chunks = chunker.chunk(long_text)

for c in chunks:
    print(f"Chunk {c.index}: {c.tokens} tokens")
```

### Workspace

```python
from utils.workspace import get_workspace_manager

wm = get_workspace_manager()
session = wm.create_session("conv-123", long_text)

# Save progress
wm.quick_chunk_save("conv-123", 1, "Content...", 500, status="done")
```

### JSON Parser

```python
from utils.json_parser import safe_parse_json

# LLM liefert schlechtes JSON
scuffed_json = "Here is the data: ```json { 'key': 'value', } ```"
data = safe_parse_json(scuffed_json)
# -> {'key': 'value'}
```
