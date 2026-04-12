# TRION Multistep Loop Implementationsplan

Erstellt am: 2026-04-09
Status: **In Umsetzung**

Aktueller Stand 2026-04-10:

- Phase 0 ist als neues, eigenstaendiges Contract-Paket begonnen:
  - `core/task_loop/contracts.py`
  - `core/task_loop/events.py`
  - `core/task_loop/guards.py`
- Der Orchestrator-Monolith wurde dabei nicht erweitert.
- Der vorhandene `core/autonomous/loop_engine.py` bleibt bewusst getrennt,
  weil er ein Tool-/ReAct-Loop ist und nicht der sichtbare Chat-first
  Aufgabenfaden.
- Contract-Tests decken State-Transitions, Eventnamen, `source_layer="task_loop"`
  und Stopbedingungen wie `max_steps_reached`, `max_runtime_reached`,
  `risk_gate_required`, `loop_detected` und fehlenden konkreten naechsten
  Schritt ab.
- Erster Chat-Adapter ist im Sync- und Stream-Pfad angebunden:
  - `core/task_loop/chat_runtime.py`
  - `core/task_loop/store.py`
  - `core/orchestrator_modules/task_loop.py`
  - `core/orchestrator_sync_flow_utils.py` enthaelt nur einen fruehen
    Short-Circuit-Aufruf.
  - `core/orchestrator_stream_flow_utils.py` spiegelt denselben fruehen
    Short-Circuit und streamt `task_loop_update`, Workspace-Updates, Content
    und Done-Event.
- Der erste Produktstand ist bewusst eng:
  - Start nur per explizitem Task-Loop-/Schrittweise-Marker oder Request-Flag
  - zwei sichere Chat-Schritte
  - sichtbarer Plan und Zwischenstand
  - `weiter` setzt fort
  - `stoppen` bricht ab
  - Workspace-Events werden mit `source_layer="task_loop"` persistiert
  - keine Tool- oder Shell-Autonomie
- Gezielter Testlauf:
  - `python -m pytest tests/unit/test_task_loop_contracts.py tests/unit/test_task_loop_events.py tests/unit/test_task_loop_guards.py`
  - Ergebnis: `19 passed`
- Aktueller gezielter Testlauf nach Sync-/Stream-Adapter:
  - `python -m pytest tests/unit/test_task_loop_contracts.py tests/unit/test_task_loop_events.py tests/unit/test_task_loop_guards.py tests/unit/test_task_loop_chat_runtime.py tests/unit/test_orchestrator_task_loop_module.py tests/unit/test_orchestrator_task_loop_stream_flow.py tests/unit/test_workspace_event_sync_path.py`
  - Ergebnis: `34 passed`
- Neue Architektur-Erkenntnis:
  - bestehende Pipeline-Bausteine sollen genutzt werden, aber nur ueber duenne
    Adapter in `core/task_loop/`
  - ThinkingLayer liefert Plan-Rohmaterial
  - Pipeline-Stages liefern spaeter Tool-Auswahl, Budget- und Domain-Signale
  - ControlContract bleibt die Risk-/Policy-Autoritaet
  - Tool-Error-Detector wird spaeter fuer Error-Zaehler und Retry-Entscheidung
    genutzt
  - `core/autonomous/loop_engine.py` bleibt getrennt, weil er ein Tool-/ReAct-
    Loop ist und nicht der sichtbare Aufgabenloop
- Phase 1b ist als deterministischer Chat-Auto-Loop ohne Tools umgesetzt:
  - `core/task_loop/reflection.py`
  - `core/task_loop/runner.py`
  - sichere Chat-Schritte laufen automatisch bis `max_steps=4`
  - nach jedem Schritt wird `task_loop_reflection` persistiert
  - `max_errors_reached`, `max_steps_reached`, `risk_gate_required`,
    `loop_detected`, `no_progress` und `no_concrete_next_step` sind als
    Stop-/Reflection-Pfade vorbereitet
  - `weiter` bleibt nur fuer manuelle/wartende Loop-Zustaende relevant
  - Zieltext-Bereinigung entfernt Task-Loop-Marker aus dem ersten Planpunkt
- Aktueller gezielter Testlauf nach Auto-Continue:
  - `python -m pytest tests/unit/test_task_loop_contracts.py tests/unit/test_task_loop_events.py tests/unit/test_task_loop_guards.py tests/unit/test_task_loop_reflection.py tests/unit/test_task_loop_runner.py tests/unit/test_task_loop_chat_runtime.py tests/unit/test_orchestrator_task_loop_module.py tests/unit/test_orchestrator_task_loop_stream_flow.py tests/unit/test_workspace_event_sync_path.py`
  - Ergebnis: `43 passed`
- Phase 1c ist als erster echter Planer-Adapter umgesetzt:
  - `core/task_loop/planner.py`
  - `core/task_loop/pipeline_adapter.py`
  - `TaskLoopSnapshot` traegt jetzt zusaetzlich `plan_steps`
  - ThinkingLayer wird bei neuem Task-Loop einmal als Plan-Rohsignal genutzt
  - Planner materialisiert strukturierte Schritte mit `title`, `goal`,
    `done_criteria`, `risk_level`, `requires_user`, `suggested_tools`
  - Tool-/Write-nahe Thinking-Signale werden im Chat-only Loop nicht
    ausgefuehrt, sondern als `risk_gate_required` vor dem riskanten Schritt
    gestoppt
  - bei fehlendem/fehlerhaftem ThinkingPlan faellt der Planer auf einen
    sicheren deterministischen Plan zurueck
- Phase 1c-Polish nach WebUI-E2E:
  - Thinking-Fallbacks wie `Fallback - Analyse fehlgeschlagen` werden nicht
    mehr in den sichtbaren Task-Loop-Plan geleakt
  - der deterministische Fallback ist nicht mehr ein generischer Smoke-Plan,
    sondern erzeugt aufgabentypische Templates fuer Pruefung, Analyse,
    Umsetzung und Default-Aufgaben
  - Pruef-/Test-Prompts erhalten Schritte wie `Pruefziel festlegen`,
    `Beobachtbare Kriterien definieren`, `Befund gegen Stopbedingungen bewerten`
    und `Befund und naechsten Produktpfad zusammenfassen`
  - generische Zieltexte wie `bearbeiten` werden im Schrittziel durch den
    brauchbaren Thinking-Intent ersetzt, wenn dieser vorhanden ist
  - Step-Antworten kommen nicht mehr aus der alten `Ziel:`/`Erfuellt:`-
    Smoke-Schablone, sondern aus `core/task_loop/step_answers.py`
  - Zwischenstaende liefern jetzt aufgabentypische Befunde, Pruefkriterien,
    Gate-Bewertungen und naechste Produktpfade fuer Pruefung, Analyse,
    Umsetzung und Default-Aufgaben
- Runtime-Befund nach WebUI-Recheck:
  - `jarvis-webui` proxyt `/api/chat` an `lobechat-adapter:8100`
  - `lobechat-adapter` bind-mountet `/home/danny/Jarvis/core` nach `/app/core`,
    laedt Python-Module aber nur beim Prozessstart
  - nach Code-Aenderungen im Chat-/Task-Loop muss mindestens
    `docker restart lobechat-adapter` laufen, sonst bleibt der alte
    Orchestrator-/Runner-Code im laufenden Prozess aktiv
  - Recheck ueber `http://localhost:8400/api/chat` mit `stream=true` liefert
    nach Restart den neuen Task-Loop-Output
- Routing-Korrektur nach weiterem WebUI-Recheck:
  - generische Woerter wie `schrittweise` oder `multistep` duerfen die normale
    Chat-Pipeline nicht mehr frueh abfangen
  - der fruehe deterministische Chat-Loop startet nur noch bei explizitem
    Task-Loop-Modus, z. B. `Task-Loop: ...`, `im Task-Loop Modus`,
    `im Multistep Modus`, `Planungsmodus` oder Request-Flag
  - normale Plan-/Pruef-Prompts laufen dadurch wieder durch Thinking/Control/
    Output statt direkt aus dem Task-Loop-Runner beantwortet zu werden
- Modell-/Control-Befund nach Pipeline-Recheck:
  - persistierte Settings standen auf nicht vorhandenen Modellen
    `compat-model:3b` und `ctrl:3b`
  - `http://ollama:11434/api/tags` enthaelt u. a. `ministral-3:8b` und
    `ministral-3:3b`
  - `config/settings.json` nutzt jetzt `THINKING_MODEL=ministral-3:8b`,
    `CONTROL_MODEL=ministral-3:3b`, `OUTPUT_MODEL=ministral-3:3b`
  - Recheck ueber `http://localhost:8400/api/chat` mit normalem
    `schrittweise`-Prompt liefert Thinking-Event, Control laeuft durch und
    Output streamt eine Modellantwort statt Task-Loop-Template
- Aktueller Stand 2026-04-11:
  - der Chat-Task-Loop streamt jetzt im echten Stream-Pfad inkrementell statt
    erst am Ende als kompletter Block:
    - `core/task_loop/runner.py` hat zusaetzlich `stream_chat_auto_loop(...)`
    - `core/orchestrator_modules/task_loop.py` hat zusaetzlich
      `stream_task_loop_events(...)`
    - `core/orchestrator_stream_flow_utils.py` nutzt im Stream-Pfad den neuen
      Generator statt einer fertigen Event-Liste
  - der erste Chunk ist jetzt der sichtbare Plan-Header, danach folgen echte
    Schritt-Deltas; die Sync-Pfade bleiben unveraendert
  - fuer HTTP-Flush ueber `uvicorn` war `asyncio.sleep(0)` zu kurz; mit
    `asyncio.sleep(0.05)` kommen die einzelnen Task-Loop-Schritte auch ueber
    `localhost:8400/api/chat` zeitlich getrennt beim Client an
  - der `lobechat-adapter` war zwischenzeitlich eine zweite Fehlerquelle:
    Typed Events und Adapter-Code liefen nach Container-Neustarts nicht immer
    auf dem Host-Code, solange nur `core/` gemountet war
  - das ist jetzt technisch geklaert:
    - `adapters/lobechat/` ist nach `/app/adapters/lobechat` gemountet
    - generische Typed Events werden im Adapter durchgereicht
    - der terminale `done`-Zweig bleibt vor generischen Metadata-Events
  - Control-Timeouts mit `control_layer_fallback_fail_closed` waren zuletzt
    keine Policy-Frage, sondern ein Runtime-Config-Mismatch:
    - `config/settings.json` stand schon auf `CONTROL_MODEL=ministral-3:3b`
    - `docker-compose.yml` ueberschrieb das aber noch mit
      `CONTROL_MODEL=ministral-3:8b`
    - nach Recreate von `lobechat-adapter` und `jarvis-admin-api` laufen beide
      Container jetzt wirklich auf `CONTROL_MODEL=ministral-3:3b`
  - wichtigster Produktbefund des Tages:
    - Thinking/Loop-Trace zeigt jetzt sichtbar, dass normale Prompts wie
      `Pruefe kurz den neuen Multistep Loop und zeige mir sichere Zwischenstaende`
      korrekt in `resolution_strategy=null`, `suggested_tools=[]` und
      `needs_memory=false` normalisiert werden
    - wenn die finale Antwort danach trotzdem ueber `Gedaechtnis`,
      `VRAM/RAM im gruenen Bereich`, erledigte Checks oder tabellarische
      Pseudo-Zwischenstaende halluziniert, passiert der Drift im normalen
      Output-Layer und nicht mehr im Task-Loop-Routing
  - das bedeutet fuer die Diagnose:
    - sichtbarer Loop-Trace funktioniert bereits als Debug-Fenster fuer
      Routing/Thinking
    - das verbleibende Problem ist nicht mehr `Cache`, Adapter oder
      `verified_plan`-Weitergabe, sondern ein noch nicht sauber greifender
      Analyse-/Output-Guard fuer diese Prompt-Klasse
  - offener Nebenbefund:
    - mehrere Container koennen Workspace-/TaskLifecycle-/Archive-Datenbanken
      nicht schreiben (`unable to open database file`)
    - das blockiert den Chat-Loop aktuell nicht direkt, erzeugt aber Rauschen
      in Logs und verhindert saubere Persistenz/Hydration
- Output-Guard-Erweiterung fuer Analyse-/Sequential-Turns:
  - der alte Output-Grounding-Guard war primaer auf Fact-Queries und
    tool-gestuetzte Antworten scharf
  - konzeptionelle Analyse-/Planungsprompts mit
    `needs_sequential_thinking=true` konnten deshalb wieder freie
    Halluzinationen ueber Gedaechtnis, VRAM/RAM, Container, Blueprints,
    Systemstatus oder erledigte Checks erzeugen
  - dafuer gibt es jetzt ein eigenes Hilfsmodul
    `core/output_analysis_guard.py`
  - der Output-Prompt fuegt fuer solche Turns einen expliziten
    `ANALYSE-GUARD` ein
  - der Stream-/Tail-Postcheck ist fuer diese Turns jetzt ebenfalls aktiv und
    puffert Reparaturen
  - unbelegte Memory-/Runtime-/Status-Behauptungen werden in einen sicheren
    Zwischenstand ohne Runtime-Fakten repariert
  - Root Cause fuer den zunaechst weiter ausbleibenden Live-Guard war danach
    noch eine zweite Bedingung im Loop-Trace-Normalizer:
    - `core/loop_trace.py` setzte `_loop_trace_mode="internal_loop_analysis"`
      zuerst nur dann, wenn der Normalizer tatsaechlich Korrekturen an
      `resolution_strategy`, `suggested_tools`, `strategy_hints` oder
      `needs_memory` vorgenommen hatte
    - bei bereits sauberen Thinking-Plaenen blieb `corrections=[]`; dadurch
      war der Prompt zwar inhaltlich ein interner Loop-/Analyse-Turn, trug aber
      keinen stabilen Marker in den Output-Pfad
    - der Fix setzt `_loop_trace_mode` und
      `_loop_trace_normalization.reason=prompt_matches_internal_loop_analysis`
      jetzt fuer interne Loop-/Analyse-Prompts immer, auch wenn
      `corrections=[]` ist
  - Live-Recheck nach diesem Fix ueber
    `Pruefe kurz den neuen Multistep Loop und zeige mir sichere Zwischenstaende`
    bestaetigt jetzt den echten End-to-End-Pfad:
    - Thinking bleibt sauber bei `resolution_strategy=null`,
      `suggested_tools=[]`, `needs_memory=false`,
      `needs_sequential_thinking=true`
    - der sichtbare Loop-Trace zeigt trotzdem
      `mode=internal_loop_analysis`, `reason=prompt_matches_internal_loop_analysis`
      und `corrections=[]`
    - der neue Trace-Schritt `Analyse-Guard im Livepfad geprueft` kommt jetzt
      mit `applicable=true`, `trigger_source=loop_trace_mode`,
      `violated=true`
    - danach erscheint sichtbar `loop_trace_correction` fuer
      `stage=output_postcheck`
    - die finale Antwort kippt nicht mehr in freie Runtime-Halluzination,
      sondern in einen sicheren Zwischenstand ohne unbelegte Runtime-Fakten
  - wichtigster neuer Produktbefund:
    - das Aktivierungsproblem des Analyse-Guards ist damit technisch geloest
    - die offene Produktfrage liegt jetzt nicht mehr bei
      `Guard greift / greift nicht`, sondern bei der Qualitaet des
      Korrekturpfads:
      - aktuell fuehrt schon ein einzelner Drift wie `runtime_inventory` zum
        generischen sicheren Zwischenstand
      - als naechster Schnitt ist deshalb weniger die Aktivierung als die
        Sichtbarkeit und Zielgenauigkeit der Reparatur relevant
- Sichtbarer Loop-Trace fuer Analyse-/Loop-Prompts:
  - interne Loop-/Analyse-Prompts laufen jetzt durch einen kleinen
    Thinking-Normalizer in `core/loop_trace.py`
  - der Normalizer faengt Fehlklassifikationen wie
    `active_container_capability`, runtime-lastige `strategy_hints`,
    `needs_memory=true` ohne expliziten Erinnerungsanker und driftende
    `suggested_tools` ab
  - der Stream-Pfad emittiert neue sichtbare Events:
    `loop_trace_started`, `loop_trace_plan_normalized`,
    `loop_trace_step_started`, `loop_trace_correction`,
    `loop_trace_completed`
  - die Jarvis-WebUI haengt diese Events an die vorhandene Planbox an und zeigt
    sie damit aufklappbar als verfolgbaren Arbeitsfaden
  - Thinking Trace zeigt zusaetzlich `Loop Mode`, `Loop Reason` und Anzahl der
    `Plan Fixes`, damit Fehlrouting leichter erkennbar ist
  - dieselbe vorhandene Plan-Box rendert jetzt auch `task_loop_update`:
    - kein neues UI-System
    - Task-Loop-Schritte erscheinen als aufklappbare Eintraege zwischen den
      normalen Assistant-Content-Bubbles
    - finale Task-Loop-States markieren die Box als abgeschlossen oder gestoppt
  - Live-Recheck mit explizitem Prompt
    `Task-Loop: Pruefe kurz den neuen Multistep Loop und zeige mir sichere Zwischenstaende`
    bestaetigt:
    - `planning`, `reflecting` und `waiting_for_user` kommen sichtbar als
      `task_loop_update` in der Plan-Box an
    - die Content-Deltas des Task-Loops werden dazwischen als normale Chat-
      Antwortbubbles gerendert
    - Task-Loop-Content wird jetzt nicht mehr in eine einzige laufende
      Assistant-Message zusammengezogen:
      - sobald `task_loop_update` aktiv ist, rendert die WebUI jeden
        Task-Loop-Content-Chunk als eigene Assistant-Bubble
      - Header, Zwischenstaende und Abschluss erscheinen dadurch als getrennte
        sichtbare Chat-Segmente statt als ein grosser Sammelblock
      - die getrennten Segmente werden auch separat im lokalen Chatverlauf
        gespeichert; fuer das Tagesprotokoll werden sie nur noch als
        zusammengefuegte Textfolge persistiert
    - die Frontend-Verkabelung fuer den echten Task-Loop ist damit bestaetigt;
      vorherige Leere in der Plan-Box war kein UI-Bug, sondern nur der normale
      Loop-Trace-Pfad ohne echte `task_loop_update`-Events
  - direkt danach trat der naechste echte Produktblocker offen zutage:
    - der explizite Task-Loop-Prompt stoppte nach Schritt 2 schon bei
      `task_loop_risk_gate_required`
    - Root Cause war nicht Reflection selbst, sondern der Planerpfad:
      `core/task_loop/planner.py` baute den Task-Loop-Snapshot aus dem rohen
      Thinking-Plan
    - dadurch konnten fuer interne Loop-/Analyse-Prompts bereits korrigierte
      Runtime-/Memory-Drifts wie `active_container_capability`,
      `needs_memory=true` und `exec_in_container` wieder als Step-Risiko in den
      Task-Loop hineinleaken
    - Folge: Schritt 3 bekam faelschlich `risk_level=needs_confirmation` und
      stoppte, obwohl der Prompt produktseitig im Chat-only Analysepfad haette
      weiterlaufen sollen
  - Fix:
    - `core/task_loop/planner.py` normalisiert den Thinking-Plan jetzt auch im
      Task-Loop-Planerpfad ueber denselben Internal-Loop-Analysis-Normalizer
    - damit basiert der Snapshot fuer diese Prompt-Klasse nicht mehr auf rohen
      Container-/Memory-/Tool-Signalen
    - gezielter Regressions-Test deckt jetzt den Fall ab: interner
      Loop-Analyse-Prompt mit rohem Runtime-Tool-Drift darf den Chat-only
      Task-Loop nicht mehr in `risk_gate_required` kippen
  - neuer Produktstand nach diesem Fix:
    - explizite Task-Loop-Prompts fuer diese sichere Analyseklasse laufen jetzt
      nicht mehr vorzeitig in das Risk-Gate
    - sichtbare Task-Loop-Schritte erscheinen getrennt im Chat statt in einer
      einzigen Assistant-Box
    - der verbleibende groessere Produktrest bleibt: Schrittantworten werden
      noch aus `core/task_loop/step_answers.py` gerendert und nicht aus einem
      echten modellgestuetzten Output pro Schritt erzeugt
  - gewuenschte Endarchitektur fuer den naechsten Schnitt:
    - nicht nur `runner -> OutputLayer`, sondern ein kleiner per-Step-
      Runtime-Schnitt in `core/task_loop/`
    - jeder Loop-Schritt soll kuenftig diesen Pfad durchlaufen:
      1. Step-Kontext bauen (`objective`, aktueller Schritt,
         `done_criteria`, bisherige verifizierte Befunde)
      2. minimalen Chat-only Step-Plan ableiten
      3. `ControlLayer.verify(...)` pro Schritt laufen lassen
      4. danach erst `OutputLayer` fuer den sichtbaren Zwischenstand aufrufen
      5. Output-Guard/Postcheck pro Schritt anwenden
      6. nur verifizierte Step-Artefakte in den naechsten Schritt mitnehmen
    - wichtig dabei:
      - der Step-Output darf nicht auf rohen freien Prosa-Text des vorherigen
        Schritts als Wahrheit bauen
      - der naechste Schritt soll nur strukturierte, sichere Artefakte erben
        (`verified_findings`, offene Unsicherheiten, naechster Schritt)
      - `step_answers.py` bleibt als Fallback erhalten
    - der feste Step-Prompt muss pro Schritt klarstellen:
      - du bist in `Task-Loop Schritt X/Y`
      - aktuell gilt Chat-only Analyse ohne Tools/Runtime-Nachweise
      - keine Runtime-/Memory-/Container-Fakten erfinden
      - konkreten sichtbaren Befund, Restunsicherheit und naechsten Schritt
        formulieren
    - dadurch wird spaetere Tool-Integration auch sauber anschlussfaehig:
      Control bleibt die Single Authority fuer Freigaben, statt dass der
      Schritt-Output implizit ueber Risiko oder Toolbedarf entscheidet
- Laufzeitbefund WebUI/Adapter:
  - der Core hat die neuen `loop_trace_*`-Events korrekt erzeugt, aber der
    laufende `lobechat-adapter` hat sie zunaechst nicht sichtbar an die WebUI
    weitergereicht
  - Ursache war nicht der Core, sondern der Container-Aufbau:
    `/home/danny/Jarvis/core` war nach `/app/core` gemountet, aber
    `adapters/lobechat/` nicht nach `/app/adapters/lobechat`
  - dadurch liefen Core-Aenderungen live, waehrend Adapter-Aenderungen trotz
    `docker restart lobechat-adapter` auf altem Image-Code blieben
  - Fix:
    - generisches Typed-Event-Passthrough in `adapters/lobechat/main.py`
    - terminaler `done`-Zweig bleibt vor dem generischen Metadata-Zweig
    - Compose-Mount `./adapters/lobechat:/app/adapters/lobechat:ro`
    - `docker compose up -d --force-recreate lobechat-adapter`
  - Recheck ueber `localhost:8100/api/chat` und `localhost:8400/api/chat`
    bestaetigt jetzt `loop_trace_started` und `loop_trace_completed` im echten
    NDJSON-Stream
- Aktueller gezielter Testlauf nach Planer-Adapter:
  - `python -m pytest tests/unit/test_task_loop_contracts.py tests/unit/test_task_loop_events.py tests/unit/test_task_loop_guards.py tests/unit/test_task_loop_planner.py tests/unit/test_task_loop_pipeline_adapter.py tests/unit/test_task_loop_reflection.py tests/unit/test_task_loop_runner.py tests/unit/test_task_loop_chat_runtime.py tests/unit/test_orchestrator_task_loop_module.py tests/unit/test_orchestrator_task_loop_stream_flow.py tests/unit/test_workspace_event_sync_path.py`
  - Ergebnis: `54 passed`
- Neuer Live-Befund fuer echten Step-Output und Streaming:
  - der Task-Loop nutzt jetzt im Stream-Pfad pro Schritt einen echten kleinen
    `Control+Output`-Runtime-Schnitt:
    - `core/task_loop/step_runtime.py` baut Step-Prompt und minimalen
      Chat-only-Plan
    - `ControlLayer.verify(...)` laeuft pro Schritt
    - danach streamt `OutputLayer.generate_stream(...)` den sichtbaren
      Zwischenstand
    - `core/task_loop/step_answers.py` bleibt als Fallback erhalten
  - erste Live-Rechecks zeigten zunaechst weiter grosse Step-Bloecke; Root
    Cause war nicht die WebUI, sondern der Backend-Pfad:
    - zunaechst landeten Analyse-Step-Antworten oft noch im Template-/Fallback-
      Eindruck
    - danach wurde sichtbar, dass der echte Step-Output bereits tokenweise aus
      dem Backend kam, aber die WebUI den Inhalt durch staendiges komplettes
      `innerHTML`-Neurendern optisch weiter wie Block-Updates wirken liess
  - Frontend-Fix:
    - `adapters/Jarvis/static/js/chat-render.js` hat jetzt einen leichten
      Streaming-Shell-Pfad fuer laufende Assistant-Nachrichten
    - waehrend des Streams wird Task-Loop-Content ueber `textContent` plus
      `requestAnimationFrame` aktualisiert
    - erst nach Abschluss wird wieder volles Markdown-/Codeblock-HTML gebaut
    - Ergebnis: die Mini-Chunks des Task-Loops wirken im Chatfenster jetzt
      sichtbar fluessiger statt wie spaete Komplettblobs
  - wichtiger Laufzeitbefund danach:
    - der Step-Output streamte im echten Pfad bereits tokenweise, brach aber
      mitten im Schritt mit `Error in input stream` ab
    - Server-seitig war dazu `ASGI callable returned without completing
      response` sichtbar
    - Root Cause war ein doppelter Timeout:
      - `OutputLayer` hatte bereits seinen eigenen per-Step-Timeout ueber
        `_output_time_budget_s`
      - `core/task_loop/step_runtime.py` legte zusaetzlich noch einen aeusseren
        harten `8s`-Timeout um den gesamten Stream
      - dieser aeussere Timeout kappte aktive Step-Antworten mitten im Token-
        Stream und riss dadurch den HTTP-Response unsauber ab
  - Fix:
    - der aeussere Timeout in `core/task_loop/step_runtime.py` wurde entfernt
    - damit bleibt nur noch der OutputLayer-Timeout als Single Authority fuer
      die Laufzeitgrenze des Schritts
    - danach liefen Live-Rechecks deutlich stabiler: Task-Loop-Schritte kamen
      sichtbar nacheinander, echte modellformulierte Zwischenstaende erschienen
      im Chat, und der harte Stream-Abbruch trat im normalen Ablauf nicht mehr
      sofort auf
  - aktueller Produktrest nach diesem Fix:
    - Infrastruktur und Streaming sind jetzt wesentlich naeher am Zielbild
    - der verbleibende Drift sitzt vor allem im inhaltlichen Step-Prompt:
      - einzelne Schritte behaupten noch unbelegte Runtime-/Container-/Metrik-
        Ursachen
      - der Guard greift dann korrekt und haengt eine sichtbare
        `[Grounding-Korrektur]` an
    - funktional ist das bereits deutlich besser als vorher, aber produktseitig
      noch nicht das gewuenschte Erlebnis
  - neuer Zwischenstand:
    - echter sichtbarer Step-Stream: ja
    - getrennte Task-Loop-Segmente im Chat: ja
    - vorzeitiger Stream-Abbruch durch doppelten Timeout: behoben
    - Template-only-Schrittantworten als alleiniger Pfad: nein
    - verbleibender Hauptrest: Prompt-Hardening und eleganterer
      Guard-/Repair-Pfad pro Schritt

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

## Wiederverwendung bestehender Pipeline

Der Task-Loop soll nicht als zweite Pipeline neben der bestehenden Chat-Pipeline
wachsen. Wiederverwendung erfolgt aber bewusst ueber Adapter, damit der
Loop-Zustand sichtbar, testbar und begrenzt bleibt.

Wiederverwenden:

- `core/layers/thinking.py`
  - liefert Intent, Komplexitaet, Memory-/Chat-History-Bedarf,
    `hallucination_risk`, `needs_sequential_thinking`, `suggested_tools` und
    `reasoning`
  - wird fuer echten Plan-Input genutzt, aber nicht direkt als Task-Loop-State
- `core/orchestrator_pipeline_stages.py`
  - `run_tool_selection_stage`
  - `run_plan_finalization`
  - `run_pre_control_gates`
  - spaeter fuer Tool-/Domain-/Budget-Signale im Loop
- `core/control_contract.py`
  - `ControlDecision`
  - `ExecutionResult`
  - `DoneReason`
  - bleibt die Policy-/Risk-Autoritaet fuer riskante oder blockierte Schritte
- `core/tool_intelligence/error_detector.py`
  - `detect_tool_error`
  - `classify_error`
  - spaeter fuer `max_errors_reached`, retryable/non-retryable und
    Fail-closed-Entscheidungen
- `core/tool_intelligence/reflection_loop.py`
  - nur spaeter fuer Tool-Retry-Planung
  - nicht als allgemeine Task-Loop-Reflection verwenden

Nicht als Basis verwenden:

- `core/autonomous/loop_engine.py`
  - bleibt getrennt
  - ist ein ReAct-/Tool-Loop mit warmem OutputLayer
  - passt erst spaeter, wenn Tool-Gates und Shell-/Tool-Autonomie stabil sind

Neue Task-Loop-Module bleiben der Ort fuer Produktzustand und Stoplogik:

- `core/task_loop/contracts.py`
- `core/task_loop/events.py`
- `core/task_loop/guards.py`
- `core/task_loop/store.py`
- `core/task_loop/chat_runtime.py`
- geplant:
  - `core/task_loop/planner.py`
  - `core/task_loop/reflection.py`
  - `core/task_loop/runner.py`
  - `core/task_loop/pipeline_adapter.py`

## Auto-Continue Zielverhalten

Der produktive Zielzustand ist nicht, dass der User nach jedem Schritt
`weiter` schreiben muss.

TRION soll automatisch fortsetzen, solange der naechste Schritt:

- konkret begruendet werden kann
- sicher ist
- keine User-Entscheidung braucht
- keinen riskanten Tool-/Shell-/Write-Pfad ausloest
- echten Fortschritt gegenueber dem vorherigen Schritt bringt
- nicht identisch mit einem vorherigen Schritt ist

Nach jedem Schritt muss TRION:

1. sichtbaren Zwischenstand erzeugen
2. reflektieren
3. Stop-/Continue-Entscheidung treffen
4. entweder automatisch weiterarbeiten oder sauber stoppen

User-Eingriff bleibt moeglich:

- `stoppen`
- Plan aendern
- Rueckfrage beantworten
- spaeter manuell fortsetzen

## Default-Limits fuer ersten Auto-Loop

Fuer den ersten echten Chat-Auto-Loop ohne Tools gelten konservative Defaults:

- `max_steps=4`
- `max_errors=4`
- `max_same_step=2`
- `max_runtime_s=90`
- `max_no_progress=2`

Harte Stopgruende:

- `completed`
- `max_steps_reached`
- `max_errors_reached`
- `max_runtime_reached`
- `loop_detected`
- `no_progress`
- `risk_gate_required`
- `unclear_user_intent`
- `no_concrete_next_step`
- spaeter bei Tools: `tool_error_no_recovery`
- spaeter bei Shell: `interactive_prompt`
- spaeter bei Shell/GUI: `open_gui_or_shell_state`

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
- `max_errors_reached`
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

#### Phase 1a: Sichtbarer Loop-Rahmen ohne Auto-Continue

Status: **umgesetzt als erster enger Produktstand**

- expliziter Start per Task-Loop-/Schrittweise-Marker oder Request-Flag
- Sync- und Stream-Pfad angebunden
- sichtbarer 2-Schritt-Plan
- `weiter` setzt fort
- `stoppen` bricht ab
- Workspace-Events mit `source_layer="task_loop"`
- keine Tool- oder Shell-Autonomie

#### Phase 1b: Chat Auto-Continue ohne Tools

Status: **umgesetzt als deterministischer Chat-Auto-Loop**

Ziel:

- keine `weiter`-Pflicht fuer sichere Chat-Schritte
- Auto-Loop bis `max_steps=4`
- nach jedem Schritt sichtbarer Zwischenstand
- Reflection nach jedem Schritt
- Stop bei Unklarheit, Risiko, fehlendem Fortschritt oder Limit

Neue Module:

- `core/task_loop/reflection.py`
- `core/task_loop/runner.py`

DoD:

- expliziter Multistep-Prompt arbeitet mindestens zwei sichere Chat-Schritte
  automatisch ab
- Stopgrund ist sichtbar
- Workspace enthaelt Start, Step, Reflection und Completion/Stop-Events
- Sync und Stream verhalten sich gleich

#### Phase 1c: Echter Planer aus ThinkingLayer

Status: **umgesetzt als erster Planer-Adapter**

Ziel:

- fester Demo-Plan wird durch echten Plan-Adapter ersetzt
- ThinkingLayer wird einmal genutzt, aber nicht direkt zum Loop-State
- `planner.py` materialisiert strukturierte Task-Loop-Schritte:
  - `step_id`
  - `title`
  - `goal`
  - `done_criteria`
  - `risk_level`
  - `requires_user`
  - `suggested_tools`

Regel:

- Wenn ThinkingLayer Tools vorschlaegt, wird der Schritt im Chat-only Loop
  nicht automatisch ausgefuehrt.
- Tool-Schritte werden bis Phase 3 als `risk_gate_required` oder
  `waiting_for_user` behandelt.

Neue Module:

- `core/task_loop/planner.py`
- `core/task_loop/pipeline_adapter.py`

Umsetzungsstand:

- ThinkingLayer wird nur bei neuem Task-Loop als Plan-Rohsignal aufgerufen.
- Normale Nicht-Task-Loop-Turns umgehen diesen Pfad vollstaendig.
- Aktive wartende Loops verwenden den bestehenden Loop-State statt erneut zu
  planen.
- Der Planner erzeugt strukturierte `plan_steps` und daraus die sichtbaren
  Plan-Titel.
- Der Runner nutzt `done_criteria` fuer bessere Schrittantworten.
- Riskante Tool-/Write-Signale stoppen im Chat-only Loop mit Risk-Gate statt
  Tools auszufuehren.
- Thinking-Fallbacks werden im sichtbaren Plan unterdrueckt.
- Der deterministische Fallback nutzt aufgabentypische Templates fuer
  Pruefung, Analyse, Umsetzung und Default-Aufgaben.
- `core/task_loop/step_answers.py` ersetzt die alte Smoke-Schrittantwort durch
  produktnaehere Zwischenstaende mit Befund, Kriterien und Gate-Bewertung.
- Task-Loop-Erkennung ist bewusst eng: normale `schrittweise`-Prompts gehen
  durch die Standard-Pipeline, explizite Task-Loop-Modi nutzen den fruehen
  Chat-Loop.
- Additiver Stream-Ausbau:
  - der echte Chat-Task-Loop kann jetzt auch im Stream-Pfad schrittweise
    senden statt erst als finalen Block
  - das ist wichtig fuer die Produktwahrnehmung, aendert aber noch nicht die
    fachliche Qualitaet der Schrittinhalte im normalen Output-Pfad

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

## Naechster Schnitt fuer morgen

Prioritaet 1: **Step-Prompt fuer echte Task-Loop-Schritte haerten**

- der groesste Architektur-Sprung ist jetzt erreicht:
  - echter per-Step-`Control+Output`-Runtime-Schnitt ist live
  - Task-Loop-Step-Content streamt sichtbar im Chat
  - der doppelte Stream-Timeout ist entfernt
- der verbleibende groesste Produktrest sitzt jetzt im Inhalt:
  - einzelne Schritte driften noch in unbelegte Runtime-/Container-/Metrik-
    Behauptungen
  - der Guard faengt das korrekt ab, aber erst nach sichtbarem Drift
- naechster sinnvoller Schnitt:
  1. Step-Prompt enger auf Chat-only Analyse und belegbare Zwischenstaende
     zuschneiden
  2. weniger freie Spekulationen ueber Ursachen, Systeme, Metriken, Health-
     Checks oder Container-State zulassen
  3. klarer auf `konkreter Befund`, `verbleibende Unsicherheit`,
     `naechster sinnvoller Schritt` zwingen
- Ziel:
  - Step-Antworten sollen von vornherein naeher am sicheren Produktstil liegen
  - Guard-Korrekturen sollen seltener noetig werden

Prioritaet 2: **Guard-/Repair-Pfad pro Schritt produktisieren**

- aktuell funktioniert der Guard technisch richtig:
  - Drift wird erkannt
  - sichtbare Korrektur wird angehaengt
- produktseitig ist der sichtbare Block
  `[Grounding-Korrektur] ... Sicherer Zwischenstand ...`
  noch zu grob
- naechster sinnvoller Schnitt:
  1. Trigger-Passage pro Schritt genauer isolieren
  2. lokale Reparatur statt globalem Ersatzblock pruefen
  3. wenn moeglich schon den problematischen Satz ersetzen, nicht die halbe
     Antwort umschreiben

Prioritaet 3: **Fallback-/Stream-Diagnostik vorerst behalten**

- neue `step_runtime`-Diagnostik hat den echten Root Cause des Stream-Abbruchs
  sichtbar gemacht
- solange Prompt-Hardening und Repair noch in Bewegung sind, ist diese
  Diagnoseebene weiter wertvoll
- spaeter erst wieder reduzieren, wenn der Schrittpfad stabil genug ist

Prioritaet 4: **Task-Loop-Aktivierung und feinere Trace-Phasen spaeter**

- Aktivierung, Plan-Box und sichtbare Zwischenphasen sind nicht mehr der
  Hauptblocker
- diese Themen bleiben sinnvoll, aber nicht mehr auf dem kritischen Pfad

Prioritaet 5: **Persistenz-Rauschen reduzieren**

- `unable to open database file` ist nicht die Hauptursache fuer das heutige
  Produktproblem, stoert aber die Fehlersuche
- morgen nur nachgelagert:
  - Schreibpfade/Volumes fuer Workspace, TaskLifecycle und Archive sauber
    pruefen
  - danach erst Persistenz-/Hydration-Themen weiter verfeinern

Kurzfassung fuer morgen:

1. per-Step `Control+Output`-Runtime fuer den Task-Loop anbinden
2. Korrekturpfad sichtbar und gezielter machen
3. Task-Loop-Aktivierungsregel finalisieren
4. sichtbare Zwischenphasen im Trace weiter ausbauen
5. erst dann Persistenz-/Hydration-Rauschen aufraeumen

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
