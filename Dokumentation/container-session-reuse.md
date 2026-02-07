# Container Session Reuse via Workspace

> **Status**: IMPLEMENTIERT (Phase 1)
> **Datum**: 2026-02-08
> **Ziel**: Container werden wiederverwendet statt bei jedem Befehl neu gestartet

---

## Problem

Jeder Befehl wie "Berechne X" startet einen NEUEN Container, obwohl bereits einer laeuft.
Ergebnis: Quota-Limits, verschwendete Ressourcen, schlechte UX.

## Architektur-Entscheidung

**Dual-Layer Ansatz:**

| Layer | Rolle | Beantwortet |
|-------|-------|-------------|
| **Workspace** | Absicht & Erinnerung | Wofuer wurde Container gestartet? Wann? In welchem Kontext? |
| **Engine** | Realitaet & Wahrheit | Laeuft er wirklich? Status? TTL? Ressourcen? |

## Design-Prinzipien

1. **Workspace = Event-Log, kein State-Store** - Keine Updates, nur neue Entries
2. **Verify darf nicht reparieren (Phase 1)** - Nur bestaetigen oder scheitern
3. **JSON im content-Feld** - Deterministische Extraktion, kein Freitext-Parsing
4. **Filter statt "letzte N"** - Aktive Container = started ohne passendes stopped
5. **Dedizierte conversation_id** - Alle Container-Events unter `_container_events`

---

## Implementierung

### 1. Container Event Builder (`_build_container_event_content`)

**Wo:** `core/orchestrator.py` (Zeile ~302)

Zentraler Helper der aus Tool-Ergebnissen Workspace-Events baut:

```python
def _build_container_event_content(self, tool_name, result, user_text, tool_args) -> Optional[dict]:
```

**container_started** (nach `request_container` mit status="running"):
```json
{
  "entry_type": "container_started",
  "content": {
    "container_id": "84653f606cbe...",
    "blueprint": "python-sandbox",
    "name": "trion_python-sandbox_1770427700",
    "purpose": "Berechne Fibonacci bis 20",
    "ttl_seconds": 600,
    "started_at": "2026-02-08T10:30:00Z"
  }
}
```

**container_stopped** (nach `stop_container` mit stopped=true):
```json
{
  "entry_type": "container_stopped",
  "content": {
    "container_id": "84653f606cbe...",
    "stopped_at": "2026-02-08T10:45:12Z",
    "reason": "user_stopped"
  }
}
```

Alle Events werden unter `conversation_id="_container_events"` gespeichert.

---

### 2. Workspace Entries schreiben (Sync + Stream)

**Wo:** `core/orchestrator.py`

**Sync-Pfad** (`_execute_tools_sync`, Zeile ~283):
```python
container_evt = self._build_container_event_content(tool_name, result, user_text, tool_args)
if container_evt:
    self._save_workspace_entry("_container_events", ...)
```

**Streaming-Pfad** (`process_stream_with_events`, Zeile ~940):
Gleiche Logik, plus `yield ("", False, ws_ev)` fuer Frontend-Updates.

---

### 3. ContextManager - Aktive Container laden

**Wo:** `core/context_manager.py` - `_load_active_containers()` (Zeile ~268)

**Logik:**
1. `workspace_list(conversation_id="_container_events", entry_type="container_started")`
2. `workspace_list(conversation_id="_container_events", entry_type="container_stopped")`
3. `stopped_ids = {JSON.parse(entry.content).container_id for entry in stopped}`
4. Filter: started ohne stopped, nur heute (`created_at.startswith(today)`)
5. Format als Text-Block

**Injection in ThinkingLayer-Kontext (Step 0.5 in `get_context()`):**
```
AKTIVE CONTAINER (Workspace-Sicht):
- python-sandbox -> 84653f606cbe (gestartet 2026-02-08T10:30:00Z, Zweck: Berechne Fibonacci)
HINWEIS: Nutze exec_in_container mit der container_id statt einen neuen Container zu starten.
```

---

### 4. Verify-Step (`_verify_container_running`)

**Wo:** `core/orchestrator.py` (Zeile ~340)

```python
def _verify_container_running(self, container_id: str) -> bool:
```

- Nutzt `container_stats(container_id)` via MCP Hub als leichtgewichtigen Ping
- `True` wenn Stats zurueckkommen, `False` bei error oder Exception
- **Phase-1 Policy: Kein Auto-Repair, kein Auto-Restart**

**Integration in Tool-Loop (beide Pfade):**
- Greift nur bei `exec_in_container`
- Ueberspringt Verify wenn `container_id == _last_container_id` (frisch gestartet)
- Bei Failure: `container_stopped` Event mit `reason: "verify_failed"`, Tool wird uebersprungen

---

## Geaenderte Dateien

| Datei | Aenderung | Status |
|-------|----------|--------|
| `core/orchestrator.py` | `_build_container_event_content()`, `_verify_container_running()`, Events in sync+stream, Verify-Step | Done |
| `core/context_manager.py` | `_load_active_containers()`, `_extract_workspace_entries()`, conv_id Filter | Done |
| `sql-memory/memory_mcp/database.py` | `list_workspace_entries()` + `entry_type` Filter (schon vorhanden) | Done |
| `sql-memory/memory_mcp/tools.py` | `workspace_list` + `entry_type` Parameter (schon vorhanden) | Done |

---

## Datenfluss

```
User: "Berechne Fibonacci bis 20"
  |
  +-- 1. ThinkingLayer: erkennt -> ["request_container", "exec_in_container"]
  |
  +-- 2. ContextManager.get_context()
  |     +-- _load_active_containers()
  |           +-- workspace_list(conv="_container_events", type="container_started")
  |           +-- workspace_list(conv="_container_events", type="container_stopped")
  |           +-- Filter: started - stopped = aktive Container
  |                 +-- Injection: "AKTIVE CONTAINER: python-sandbox -> abc123..."
  |
  +-- 3. Tool Execution (Orchestrator)
  |     +-- request_container("python-sandbox")
  |     |     +-- -> _build_container_event_content() -> workspace_save(container_started)
  |     |
  |     +-- VERIFY: _verify_container_running(abc123)
  |     |     +-- OK   -> exec_in_container(abc123, "python3 -c ...")
  |     |     +-- FAIL -> container_stopped(verify_failed) + skip
  |     |
  |     +-- exec_in_container(abc123, "python3 -c ...")
  |
  +-- 4. OutputLayer: Antwort mit Ergebnis
```

## Naechster Schritt: Container-Reuse durch ThinkingLayer

Wenn ThinkingLayer den Container-Kontext sieht:
```
AKTIVE CONTAINER (Workspace-Sicht):
- python-sandbox -> abc123 (gestartet 10:30, Zweck: Berechnung)
HINWEIS: Nutze exec_in_container mit der container_id statt einen neuen Container zu starten.
```

...sollte es `["exec_in_container"]` statt `["request_container", "exec_in_container"]` vorschlagen.

**Das haengt vom ThinkingLayer (deepseek-r1:8b) ab.** Die Prompt-Instruktion ist im Kontext.
Falls das Modell das nicht zuverlaessig macht, waere Phase 2: Orchestrator-Level Override
(wenn aktiver Container mit passendem Blueprint existiert -> request_container ueberspringen).

---

## Test-Ergebnisse (2026-02-07)

| Test | Status | Details |
|------|--------|---------|
| workspace_list mit entry_type Filter | PASS | Filtert korrekt nach container_started/container_stopped |
| workspace_save container_started | PASS | Events werden mit korrektem JSON gespeichert |
| _load_active_containers() | PASS | Erkennt 1 aktiven Container, gibt formatierten Text zurueck |
| ContextManager Injection | PASS | sources=['daily_protocol', 'active_containers'] im Log |
| OutputLayer Container-Awareness | PASS | Antwortet mit korrekter container_id und exec_in_container Empfehlung |
| Container Start/Stop via MCP | PASS | request_container und stop_container funktionieren |

**Bekanntes Problem:** ThinkingLayer (deepseek-r1:8b) erkennt Container-Tools nicht zuverlaessig
trotz Prompt-Regeln. Keyword-Fallback im Orchestrator sollte greifen, tut es aber nicht immer.
Dies ist ein vorbestehendes Problem, nicht durch Session Reuse verursacht.

---

## Offene Punkte (Phase 2+)

- [ ] TTL-Expiry Tracking (Container Commander callback -> container_stopped Event)
- [ ] Orchestrator-Level Override: request_container ueberspringen wenn passender Container aktiv
- [ ] Auto-Repair in Verify-Step (Phase 2: Container neu starten statt fail)
- [ ] Konversations-Grenzen: Container-Events an User-conversation_id binden?
- [ ] Multi-Container Auswahl: Was wenn 2 python-sandbox laufen?
- [ ] ThinkingLayer Tool-Erkennung verbessern (Container-Keywords werden ignoriert)

---

*Letzte Aktualisierung: 2026-02-07 - Phase 1 getestet und verifiziert*
