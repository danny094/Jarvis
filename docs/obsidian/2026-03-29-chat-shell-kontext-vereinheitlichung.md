# TRION Chat↔Shell Kontext-Vereinheitlichung

Erstellt am: 2026-03-29
**Implementiert am: 2026-03-29 — Phase 1 + Phase 2 abgeschlossen, Phase 2b (Memory+Identity) implementiert**

Basis-Analysen: [[20-TRION-Chat-Shell-Memory-und-Kontext-Analyse]] / [[21-TRION-Chat-Shell-CIM-und-Control-Analyse]] / [[22-TRION-Chat-Shell-Implementationsplan]]

---

## Implementierungsstand (2026-03-29)

### Erledigt

**Neues Modul: `container_commander/shell_context_bridge.py`**
- `build_mission_state(conversation_id)` — lädt beim Shell-Start den kompakten Chat-Kontext (max. 600 Zeichen, fail-open bei Fehler)
- `save_shell_session_summary(...)` — ersetzt alten `_save_shell_summary_event()`, schreibt `shell_session_summary`-Event mit strukturierten Feldern (goal, findings, changes_applied, open_blocker, step_count)
- `save_shell_checkpoint(...)` — speichert Zwischenstände als `shell_checkpoint`-Event (für spätere Nutzung bei Mehrschritt-Sessions)

**`core/context_cleanup.py`** — neue Handler in `_apply_event()`:
- `shell_session_summary` + `trion_shell_summary` (Alias für Rückwärtskompatibilität) → `SHELL_SESSION_SUMMARY`-TypedFact + Container-Entity-Update
- `shell_checkpoint` → `SHELL_CHECKPOINT`-TypedFact + Container-Entity-Update

**`adapters/admin-api/commander_api/containers.py`**:
- Stop: `save_shell_session_summary()` aus Bridge (statt altem internem Helper)
- Start: `build_mission_state()` lädt Chat-Kontext → wird als `mission_state` in Session gespeichert
- Step: `mission_state` wird als `User & chat context`-Block in den System-Prompt injiziert
- System-Prompt: TRION spricht User beim Namen an wenn Name bekannt

**`build_mission_state()` — Phase 2b (Memory+Identity):**
- Quelle 1: Persona (`user_name`, `language`, `user_context`) — sync, immer verfügbar
- Quelle 2: SQL-Memory `user_facts` via `memory_fact_load` — async-wrapped, 2s timeout, fail-open
- Quelle 3: Workspace Compact Context (NOW/RULES/NEXT) — wie bisher
- Max. 800 Zeichen gesamt (vorher 600)

**Tests** (31 neue Contract-Tests, alle grün):
- `tests/unit/test_shell_context_bridge_contract.py` (17 Tests — inkl. Identity + Memory)
- `tests/unit/test_context_cleanup_shell_events.py` (14 Tests)

### Noch offen (nächste Phasen aus [[22-TRION-Chat-Shell-Implementationsplan]])

- Phase 3: `exec_in_container` stdout-Snippet ins `container_exec`-Event aufnehmen
- Phase 3: Shell-Control als offizieller Modus kapseln (`engine_shell_control.py`)
- Phase 4: Safety-Schnitt Shell vs. Chat explizit trennen
- Phase 5: UI-Kontinuitätsanzeigen (Shell-Start/Stop im Chat sichtbar machen)
- Phase 6: Mikro-Loops / Shell-Teilautonomie (erst nach stabiler Basis)

### Bekannte Einschränkung

`save_shell_checkpoint()` ist implementiert aber noch nicht aufgerufen — der Aufrufer in `containers.py` muss noch entscheiden bei welchen Steps (z.B. alle 5 oder bei `shell_change_applied`) ein Checkpoint sinnvoll ist. Erst aktivieren wenn Phase 3 (Shell-Control-Modus) steht, damit die Frequenz kontrollierbar bleibt.

---

## Zielbild

Chat und Shell teilen dieselbe TRION-Identität, denselben Erinnerungskanal und denselben Aufgabenkontext — ohne dass die Ausführungsprimitive (MCP-Tool vs. PTY-Session) verändert werden.

Die zwei Ausführungswege (`exec_in_container` aus Chat und `trion-shell` aus Terminal) bleiben getrennt — das ist technisch korrekt und sinnvoll. Was vereinheitlicht wird, ist ausschließlich die **Kontextschicht**.

---

## Ist-Zustand (Code-Stand 2026-03-29)

### Weg 1: Chat → `exec_in_container`

- Orchestrator (`orchestrator.py:3587`) speichert nach jedem `exec_in_container`-Call ein `container_exec`-Workspace-Event
- `context_cleanup.py:609` kennt `container_exec` bereits und verarbeitet es (exit_code, container state)
- **Lücke**: stdout/stderr landen nicht im Event → kein Nachweis was tatsächlich ausgegeben wurde

### Weg 2: Terminal → `trion-shell`

- `api_trion_shell_start` (`containers.py:719`): erstellt Session im RAM, bekommt `conversation_id`, aber **kein Chat-Kontext** fließt in die Session ein
- `api_trion_shell_step` (`containers.py:784`): nutzt nur lokalen Session-State (step_history, commands, user_requests) — **kein compact context, keine Workspace-Events aus vorherigen Chat-Turns**
- `api_trion_shell_stop` (`containers.py:1094`): speichert einmalig `trion_shell_summary` Event
- **`context_cleanup.py` kennt `trion_shell_summary` nicht** → das Event wird im normalen Chat komplett ignoriert

### Fazit

```
Chat + exec_in_container  →  container_exec Event (partial) → context_cleanup kennt es ✓
trion-shell               →  trion_shell_summary Event      → context_cleanup kennt es ✗
trion-shell start         →  kein Chat-Kontext              → Shell startet wie neu       ✗
```

---

## Eingriffspunkte

### 1. `context_cleanup.py` — neue Event-Typen

**Datei:** `core/context_cleanup.py`

Neue `elif`-Blöcke in `_apply_event()` nach dem bestehenden `observation/task/note`-Block:

```
elif event_type == "shell_session_summary":
    # kompakte Facts aus Shell-Session in TypedState schreiben
    # container-State updaten (last_action, last_change)
    # TypedFact mit goal + findings + changes + blocker anlegen

elif event_type == "shell_checkpoint":
    # lightweight update: aktuelles Ziel, letzter Befehl, Blocker
    # kein eigener TypedFact (zu häufig), nur state.upsert_entity
```

Beide müssen **fail-closed** sein (try/except wie alle anderen Digest-Handler).

**Warum hier:**
- Das ist der einzige Ort, wo Workspace-Events semantisch in den Chat-Kontext fließen
- Konsistent mit dem etablierten Pattern der anderen Event-Handler
- Kein neues Infrastruktur nötig

---

### 2. `containers.py` — Shell-Stop: Event-Type anpassen

**Datei:** `adapters/admin-api/commander_api/containers.py`

`_save_shell_summary_event()` (`containers.py:168`):

- Event-Type von `trion_shell_summary` → `shell_session_summary`
- `event_data` um folgende Felder erweitern (bereits zum Teil vorhanden in `summary_parts`):
  - `goal` — initiales Ziel der Session
  - `findings` — was wurde festgestellt
  - `changes_applied` — was wurde tatsächlich geändert
  - `open_blocker` — was blieb offen
  - `container_id`, `blueprint_id`, `container_name` — bereits vorhanden
  - `step_count` — wie viele Schritte

Rückwärtskompatibilität: alter `trion_shell_summary` Type kann parallel im `context_cleanup.py` als Alias behandelt werden (passthrough).

---

### 3. `containers.py` — Shell-Start: Mission State laden

**Datei:** `adapters/admin-api/commander_api/containers.py`

`api_trion_shell_start` (`containers.py:719`):

Beim Start zusätzlich `build_mission_state(conversation_id)` aufrufen → kompakten Chat-Kontext laden und als `mission_state` in der Session speichern.

Was `mission_state` enthält (maximal ~600 Zeichen):
- aktiver Container (falls bekannt aus conversation state)
- letztes Ziel / letzter Intent aus compact context
- offene Gates / bekannte Blocker aus NOW-Block
- NICHT: rohe Chat-Messages

---

### 4. `containers.py` — Shell-Step: Mission State nutzen

**Datei:** `adapters/admin-api/commander_api/containers.py`

`api_trion_shell_step` (`containers.py:784`) — System-Prompt-Block erweitern:

Vor dem Runtime-Context-Block einen kleinen `Mission context`-Abschnitt einfügen wenn `session.mission_state` vorhanden:

```
Mission context from ongoing chat:
{mission_state}
```

Maximal 600 Zeichen, danach abschneiden. Kein roher Chat-Verlauf.

---

### 5. `orchestrator.py` — `exec_in_container` stdout sichern (optional, Phase 2)

**Datei:** `core/orchestrator.py:3598`

`container_exec`-Event um `stdout_snippet` (max. 300 Zeichen, nur bei exit_code != 0 oder wenn Ausgabe relevant) erweitern, damit der Chat-Kontext nicht nur den exit_code sieht, sondern auch eine kurze Ausgabe.

Aktuell wird nur gespeichert: `command`, `exit_code`, `container_id`, `blueprint_id`.

---

## Neues Modul: `container_commander/shell_context_bridge.py`

**Ziel:** Alle Chat↔Shell-Kontext-Logik aus `containers.py` herausziehen in ein dediziertes Modul.

Folgt dem etablierten `engine_*.py` / `mcp_tools_*.py` Namensmuster aus dem Prep-Schnitt (2026-03-26).

### Funktionen

```python
async def build_mission_state(conversation_id: str) -> str:
    """
    Fetcht den Compact Context für conversation_id via build_small_model_context().
    Gibt maximal 600 Zeichen zurück.
    Bei Fehler: leerer String (fail-open, Shell funktioniert weiterhin).
    """

def save_shell_session_summary(
    *,
    conversation_id: str,
    container_id: str,
    blueprint_id: str,
    container_name: str,
    goal: str,
    findings: str,
    changes_applied: str,
    open_blocker: str,
    step_count: int,
    commands: list[str],
    user_requests: list[str],
    final_stop_reason: str,
    summary_parts: dict,
) -> None:
    """
    Speichert shell_session_summary als Workspace-Event.
    Ersetzt _save_shell_summary_event() in containers.py.
    """

def save_shell_checkpoint(
    *,
    conversation_id: str,
    container_id: str,
    goal: str,
    finding: str,
    action_taken: str,
    blocker: str,
    step_count: int,
) -> None:
    """
    Speichert shell_checkpoint als Workspace-Event.
    Wird optional nach definierten Schritten (z.B. alle 5 Steps) aufgerufen.
    """
```

### Warum eigenes Modul (nicht direkt in containers.py)

- `containers.py` ist bereits 1455 Zeilen
- Kontext-Brücken-Logik ist fachlich eigenständig (kein PTY, kein Shell-Control)
- Vereinfacht spätere Tests (Mocking von `build_small_model_context` isoliert)
- Passt zu bestehender Konvention: kleine, fokussierte Hilfsmodule

---

## Was zu beachten ist

### 1. Compact, nicht Volltranskript

`build_mission_state()` darf **niemals** rohe `request.messages` in den Shell-Prompt spiegeln. Nur das was `build_small_model_context()` zurückgibt — maximal 600 Zeichen.

### 2. Fail-open für Mission State

Wenn `build_mission_state()` fehlschlägt (z.B. keine Workspace-Events vorhanden, leere Konversation), gibt es einen leeren String zurück. Die Shell funktioniert dann wie heute — kein Absturz, kein Hard-Error.

### 3. context_cleanup.py ist deterministisch

Neue Event-Handler müssen das exakte Pattern der bestehenden Digest-Handler befolgen: `try/except` → `pass` im Fehlerfall. Kein raise, kein Log-Noise bei fehlenden Feldern.

### 4. Event-Type Rückwärtskompatibilität

`trion_shell_summary` wird von bestehenden Deployments bereits gespeichert. `context_cleanup.py` soll beide Typen kennen:

```python
elif event_type in ("shell_session_summary", "trion_shell_summary"):
    # identische Verarbeitung
```

### 5. Async-Boundary in shell_context_bridge.py

`build_mission_state()` ist async (ruft `build_small_model_context()` auf, das intern `hub.call_tool()` nutzt). Der Aufrufer in `api_trion_shell_start()` ist bereits async → kein Problem.

`save_shell_session_summary()` und `save_shell_checkpoint()` sind sync (wie der bestehende `_save_shell_summary_event()`).

### 6. Session-State bleibt im RAM

`_TRION_SHELL_SESSIONS` wird nicht verändert. `mission_state` ist ein zusätzliches Feld im Session-Dict. Kein neuer persistenter Speicher.

### 7. Checkpoint-Frequenz begrenzen

`save_shell_checkpoint()` **nicht** nach jedem Step aufrufen — das würde den Compact Context mit Shell-Telemetrie überfluten. Sinnvoll: alle 5 Steps oder nur bei `shell_change_applied`.

---

## Umsetzungsreihenfolge

### Phase 1: Memory Bridge Shell → Chat (sofortige Wirkung auf Chatseite)

1. `context_cleanup.py`: Handler für `shell_session_summary` + `trion_shell_summary` alias
2. `container_commander/shell_context_bridge.py`: `save_shell_session_summary()` + `save_shell_checkpoint()`
3. `containers.py`: `_save_shell_summary_event()` durch `shell_context_bridge.save_shell_session_summary()` ersetzen

**Ergebnis:** Nach einer Shell-Session weiß der nachfolgende Chat was in der Shell passiert ist.

---

### Phase 2: Mission State Handoff Chat → Shell (sofortige Wirkung auf Shell-Seite)

1. `container_commander/shell_context_bridge.py`: `build_mission_state()` implementieren
2. `containers.py` `api_trion_shell_start()`: `mission_state` laden und in Session speichern
3. `containers.py` `api_trion_shell_step()`: `mission_state` in System-Prompt injizieren

**Ergebnis:** Shell kennt beim Start das laufende Ziel aus dem Chat. Kein "neues Modell"-Gefühl.

---

### Phase 3: exec_in_container stdout (optional, bei Bedarf)

1. `orchestrator.py:3598`: `stdout_snippet` ins `container_exec` Event aufnehmen
2. `context_cleanup.py:609`: `container_exec`-Handler um `last_stdout` erweitern

**Ergebnis:** Chat-TRION hat nicht nur exit_code, sondern auch kurzen Ausgabe-Kontext bei direkten Container-Exec-Calls.

---

## Betroffene Dateien (Zusammenfassung)

| Datei | Änderung |
|---|---|
| `core/context_cleanup.py` | neue Handler: `shell_session_summary`, `trion_shell_summary` alias, `shell_checkpoint` |
| `container_commander/shell_context_bridge.py` | **NEU**: `build_mission_state`, `save_shell_session_summary`, `save_shell_checkpoint` |
| `adapters/admin-api/commander_api/containers.py` | Start: mission_state laden; Step: injizieren; Stop: bridge nutzen |
| `core/orchestrator.py` | (Phase 3, optional) stdout_snippet in container_exec Event |

---

## Tests

Neue Contract-Tests in `tests/unit/`:

- `test_shell_context_bridge_session_summary.py` — save_shell_session_summary schreibt korrektes Event
- `test_shell_context_bridge_mission_state.py` — build_mission_state liefert kompakten String, fail-open bei Fehler
- `test_context_cleanup_shell_events.py` — shell_session_summary + shell_checkpoint erzeugen erwartete TypedFacts
- `test_context_cleanup_trion_shell_summary_alias.py` — alter Event-Type bleibt kompatibel

---

## Nicht in diesem Plan

- Shell-Control-Modus formalisieren (Phase 3 aus Doc 22) — eigenständiges Thema
- Micro-Loops / Shell-Autonomie — erst nach stabiler Memory-Bridge
- UI-Kontinuitäts-Anzeigen — eigenständiges Frontend-Thema
