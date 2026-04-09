# TRION Multistep Loop Implementationsplan

Erstellt am: 2026-04-09
Status: **Geplant**

## Zielbild

TRION soll Aufgaben nicht nur in einem einzelnen Chat-Turn beantworten,
sondern kontrolliert in mehreren Schritten loesen koennen:

1. Aufgabe verstehen
2. Plan erstellen oder aktualisieren
3. naechsten Schritt ausfuehren
4. Zwischenstand sichtbar antworten
5. Ergebnis bewerten
6. falls noetig weiterarbeiten
7. final abschliessen oder sauber stoppen

Das Ziel ist ein Verhalten wie bei einem agentischen Arbeitsmodus:

- nachdenken
- Plan zeigen
- handeln
- Ergebnis erklaeren
- naechsten Schritt ableiten
- weiterarbeiten
- bis Aufgabe geloest, blockiert oder riskant ist

Der erste produktive Zielkanal ist **das normale Chatfenster**. Die Shell folgt
erst spaeter, wenn der Chat-Loop stabil und gut beobachtbar ist.

## Abgrenzung

Nicht gemeint ist:

- blinde Autonomie ohne Stopbedingungen
- Shell-Befehle in Endlosschleifen
- ein versteckter Hintergrundagent ohne sichtbaren Zustand
- sofortiger Vollausbau fuer alle Tool- und Shell-Aktionen

Gemeint ist ein kontrollierter Aufgabenloop mit sichtbarem Planungsfaden,
klaren Stopgruenden und Nutzerkontrolle.

## Kernkonzept

Der Loop braucht einen eigenen Aufgabenzustand:

- `objective_id`
- `conversation_id`
- `plan_id`
- `step_index`
- `state`
  - `planning`
  - `answering`
  - `executing`
  - `reflecting`
  - `waiting_for_user`
  - `blocked`
  - `completed`
  - `cancelled`
- `current_plan`
- `completed_steps`
- `pending_step`
- `last_user_visible_answer`
- `stop_reason`
- `risk_level`
- `tool_trace`
- `workspace_event_ids`

Dieser Zustand muss in Workspace-/Memory-Events nachvollziehbar sein, nicht nur
im fluechtigen Request-Kontext.

## Planungsmodus als Faden

Der Planungsmodus soll als sichtbarer Faden fuer den Loop dienen.

Wichtige Regeln:

- ein Plan ist kein einmaliger Textblock, sondern ein aktualisierbarer
  Aufgabenfaden
- jeder Loop-Schritt referenziert den aktuellen Plan
- TRION darf den Plan nach neuen Erkenntnissen anpassen
- Plan-Aenderungen muessen sichtbar und begruendet sein
- der User muss jederzeit erkennen:
  - woran TRION gerade arbeitet
  - welcher Schritt abgeschlossen ist
  - welcher Schritt als naechstes kommt
  - ob TRION wartet, blockiert ist oder weiterarbeitet

Bestehende `planning_*`-Events koennen dafuer genutzt werden, muessen aber klar
zwischen Sequential-Planning und Master-/Task-Planning unterscheiden:

- `source_layer="sequential"` fuer Denk-/Reasoning-Schritte
- `source_layer="master"` oder `source_layer="task_loop"` fuer Aufgabenloop-
  Schritte

## Chat-first Architektur

Phase 1 soll komplett im Chatfenster funktionieren.

Minimaler Ablauf:

1. User stellt eine Aufgabe, die mehrere Schritte braucht.
2. Orchestrator erkennt `task_loop_candidate=true`.
3. TRION erstellt einen kurzen Plan und zeigt ihn im Chat/Workspace.
4. TRION fuehrt genau einen sicheren Schritt aus.
5. TRION antwortet mit Zwischenstand und naechstem geplanten Schritt.
6. Wenn der Schritt sicher automatisch fortsetzbar ist, laeuft der Loop weiter.
7. Wenn Risiko, Unklarheit oder User-Entscheidung entsteht, stoppt TRION mit
   `waiting_for_user`.

Wichtig: Die Zwischenantworten sind Teil des Produktverhaltens, kein Debuglog.
Sie muessen kurz, konkret und fuer den User steuerbar sein.

## Shell erst spaeter

Shell-Autonomie wird bewusst nachgelagert.

Voraussetzungen vor Shell-Loop:

- Chat-Multistep-Loop ist stabil
- Mission-State und Shell-Session-State sind gekoppelt
- Shell-Control-Profile ist gekapselt
- Risk-Gates fuer Write-/GUI-/Long-running-Aktionen sind hart
- Stopbedingungen sind getestet
- Shell-Checkpoints werden live in Workspace-/Planungsfaden gespiegelt

Der erste Shell-Loop darf nur kontrollierte Mikro-Sequenzen ausfuehren, z. B.:

- Diagnose lesen
- Status pruefen
- harmlose Verifikation ausfuehren
- Ergebnis zusammenfassen

Keine riskanten Writes ohne explizite Freigabe.

## Stopbedingungen

Der Loop muss hart stoppen bei:

- `max_steps_reached`
- `max_runtime_reached`
- `loop_detected`
- wiederholtem identischem Tool-/Shell-Schritt
- fehlendem Fortschritt
- riskanter Aktion ohne Freigabe
- unklarer Nutzerabsicht
- Tool-Fehler ohne sicheren Recovery-Schritt
- interaktivem Prompt
- offenem GUI-/Shell-Zustand
- Modell kann keinen konkreten naechsten Schritt begruenden

Jeder Stop braucht einen stabilen `stop_reason` und eine sichtbare
User-Antwort.

## UI-Anforderungen

Im Chatfenster:

- Plan kurz sichtbar machen
- aktuellen Schritt markieren
- Zwischenantworten nicht als endgueltige Antwort tarnen
- "weiter machen" / "stoppen" / "Plan aendern" als natuerliche User-Pfade

Im Workspace:

- Planungsfaden replaybar machen
- abgeschlossene Schritte anzeigen
- aktuellen Status anzeigen
- Stopgrund anzeigen

Spaeter in der Shell:

- Mission-State sichtbar halten
- Shell-Schritte als Checkpoints spiegeln
- Shell-Ende immer mit "geprueft / geaendert / offen" zusammenfassen

## API- und Event-Skizze

Moegliche interne Events:

- `task_loop_started`
- `task_loop_plan_updated`
- `task_loop_step_started`
- `task_loop_step_answered`
- `task_loop_step_completed`
- `task_loop_reflection`
- `task_loop_waiting_for_user`
- `task_loop_blocked`
- `task_loop_completed`
- `task_loop_cancelled`

Moegliche API-/Runtime-Erweiterungen:

- `POST /api/task-loops`
- `GET /api/task-loops/{objective_id}`
- `POST /api/task-loops/{objective_id}/continue`
- `POST /api/task-loops/{objective_id}/cancel`
- `POST /api/task-loops/{objective_id}/revise-plan`

Das muss nicht zwingend als neues API-Subsystem starten. Fuer die erste Phase
kann es auch direkt im Chat-Orchestrator beginnen, solange die Event- und
State-Contracts sauber gepinnt sind.

## Implementationsphasen

### Phase 0: Contract und Doku

- State-Maschine finalisieren
- Eventnamen festlegen
- Stopgruende festlegen
- UI-Semantik fuer Zwischenantworten festlegen
- Tests als Contract vorbereiten

### Phase 1: Chat-Multistep ohne Shell

- Task-Loop-Erkennung im Orchestrator
- Plan erzeugen und persistieren
- einen Schritt ausfuehren
- Zwischenantwort erzeugen
- Reflection/Continue-Entscheidung treffen
- harte Step-/Runtime-Limits
- User kann abbrechen oder Plan aendern

### Phase 2: Planungsfaden und Workspace-Integration

- Workspace-Replay fuer Task-Loop-Events
- Plan-Status im Chat sichtbar
- Hydration nach Reload
- saubere Trennung von Sequential-Planning und Task-Loop-Planning

### Phase 3: Tool-Loop-Haertung

- Tool-Trace pro Schritt
- Retry nur mit veraenderter Strategie
- Fail-closed bei unsicherer Recovery
- Control-Gates fuer riskante Tools
- klare User-Fragen bei Blockade

### Phase 4: Shell-Mikro-Loops

- Shell-Control-Profile offiziell kapseln
- Shell-Schritte checkpointen
- nur harmlose Diagnose-/Read-Only-Sequenzen erlauben
- Risk-Gates fuer Writes und GUI-Aktionen
- Stop bei Prompt, Wiederholung oder fehlendem Fortschritt

### Phase 5: Stabilisierung und Produktpolish

- bessere UI fuer "weiter machen"
- Plan-Revisionen komfortabler machen
- Laufzeitmetriken
- Regression-Suite fuer Chat-Loop und Shell-Loop

## Erste DoD

Ein erster stabiler Stand ist erreicht, wenn:

- TRION im Chat eine mehrschrittige Aufgabe mit sichtbarem Plan starten kann
- mindestens zwei aufeinanderfolgende sichere Schritte mit Zwischenantworten
  ausgefuehrt werden koennen
- der Planungsfaden im Workspace nachvollziehbar bleibt
- `continue`, `waiting_for_user`, `completed`, `blocked` unterscheidbar sind
- `max_steps_reached` und `loop_detected` getestet sind
- keine Shell-Autonomie dafuer notwendig ist

## Leitplanke

Dieser Strang ersetzt den alten vagen Punkt "spaeter Mikro-Loops". Die neue
Reihenfolge ist:

1. Chat-Multistep-Loop
2. sichtbarer Planungsfaden
3. robuste Stop-/Control-Gates
4. erst danach Shell-Mikro-Loops
