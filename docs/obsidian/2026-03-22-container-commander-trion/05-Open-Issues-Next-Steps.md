# Offene Punkte und nächste Schritte

## Aktueller Prioritätswechsel

Stand: 2026-03-27

Der fruehere Prioritaetswechsel ist inzwischen **abgearbeitet**:

- `runtime-hardware` v0 ist live
- `Simple > Neues Blueprint` nutzt den neuen Hardware-Pfad bereits praktisch
- `gaming-station` war dafuer der erste echte Realtest
- `Simple > Neues Blueprint` unterstuetzt inzwischen auch ein eigenes Dockerfile direkt in der Uebersicht

Der aktuelle Fokus liegt jetzt auf **Produktisierung und Härtung der Live-Pfade**:

1. Storage-Broker-Repartitionierung / `mkfs` / Label-Anzeige sauberziehen
2. Commander-/UI-Flows auf echte Nutzerpfade glätten
3. Live-Pfade weiter vereinheitlichen

Archivhinweis 2026-04-01:

- Der fruehere `gaming-station`-/Gaming-Container-Zweig ist gestoppt und archiviert.
- Die Detailnotizen dazu liegen gesammelt unter [[Archiv/2026-04-gaming-station/00-Archiv-Index|Archiv/2026-04-gaming-station]].

Freeze-Hinweis 2026-04-09:

- Gaming / Sunshine / Moonlight ist komplett aus den aktiven Arbeitssträngen
  herausgenommen.
- Der Stand bleibt eingefroren und nur noch historisch referenziert.
- Keine neuen Next Steps, keine Live-Härtung und keine weiteren Tests in diesem
  Themenblock, sofern der Strang nicht explizit wieder aufgetaut wird.

## Was jetzt gut funktioniert

- Container-Commander ist deutlich stabiler
- Container-Query-Klassentrennung fuer Inventar / Blueprint / Binding ist jetzt
  im Chatpfad sichtbar verankert
- `container_addons` sind jetzt explizit an `query_class` gekoppelt statt nur
  lose an Freitext
- der Output-Contract trennt Runtime-Inventar, Blueprint-Katalog und
  Session-Binding jetzt sichtbar
- lokaler Live-Recheck gegen echtes Ollama + reale Runtime-/Blueprint-Daten
  liefert fuer diese drei Fragetypen jetzt contract-konforme Endantworten
- `runtime-hardware` ist als eigener v0-Service live
- StorageBroker und Commander sind näher zusammengerückt
- TRION kann direkt im Containerkontext analysieren
- `trion shell` ist praktisch nutzbar
- container-spezifisches Shellwissen ist vorbereitet
- der Commander-/Quota-Stand wird jetzt gegen den realen Docker-Zustand synchronisiert
- Bind-Mount-Hostpfade unter `/data/...` werden jetzt nativ über `storage-host-helper` vorbereitet

## Offene Punkte

### Portable Endpoints / Publish-Hygiene

- Neuer Produktisierungsstrang dokumentiert in
  [[2026-04-07-portable-endpoints-und-publish-hygiene]].
- Obsidian-Leak-Audit und Redaktionsstand dokumentiert in
  [[2026-04-07-obsidian-doc-leak-audit]].
- Stand 2026-04-07:
  - zentraler Endpoint-Resolver eingefuehrt
  - feste `172.17.0.1`-Bruecken aus den produktiven Runtime-/Gateway-Pfaden
    entfernt
  - `runtime-hardware`, `admin-api` und `ollama` nutzen jetzt eine portable
    Kandidatenreihenfolge aus:
    - expliziter Env-URL
    - internem Service-Namen
    - dynamischem Gateway
    - `host.docker.internal`
    - Loopback
  - `OLLAMA_BASE` faellt container-aware nicht mehr pauschal auf
    `host.docker.internal` zurueck
  - Obsidian-Notizen auf echte Host-/Pfad-Leaks redigiert
  - getrackte Logs, Memories, Session-Handoffs und `__pycache__`-Artefakte aus
    dem Git-Index entfernt
  - `sanitize_for_publish.sh --check` ist fuer den aktuellen Index jetzt gruen
- Verifiziert ueber:
  - `tests/unit/test_service_endpoint_resolver.py`
  - `tests/unit/test_runtime_hardware_gateway_contract.py`
  - `tests/unit/test_container_commander_hardware_resolution.py`
  - `tests/unit/test_scope4_compute_routing.py`
  - Gesamt: `43 passed`
- Offener Rest:
  - lokale Dev-/Ops-Skripte und einzelne UI-/MCP-Defaults weiter aufraeumen
  - Publish-Hygiene als automatisierten Clean-/Secret-Scan-Workflow verankern
  - tracked Logs/Memory-Artefakte vor einer oeffentlichen Repo-Freigabe
    tatsaechlich ausraeumen; der erste Sanitizer-Check meldet hier schon
    reale Treffer

### Control Authority / Container-Fallback-Drift

- Neuer dokumentierter Live-Befund: `Control Layer: Approved` ist bei Container-Requests noch kein stabiler Endzustand.
- Der konkrete Drift ist in [[2026-04-01-control-authority-drift-approved-fallback-container-requests]] festgehalten.
- Problemkette aktuell:
  - UI rendert nur rohes `approved`
  - Blueprint-/Routing-Gate kann `request_container` spaeter effektiv entwerten
  - Executor codiert Routing oft als technisches `unavailable`
  - Output-Grounding kippt danach in den generischen Tool-/Evidence-Fallback
- Besonders sichtbar wurde das bei:
  - `TRION Home Container starten`
  - `TRION Home Workspace starten`
- Offene Folgearbeit fuer spaeter:
  - reconcilierten Control-Endzustand im UI anzeigen statt nur `Approved/Rejected`
  - Routing-Block semantisch von technischem `unavailable` trennen
  - Output-Grounding fuer Routing-Block von Tech-Failure entkoppeln
  - harten Home-Start/Reuse-Fast-Path fuer `TRION Home` einfuehren statt generischem `request_container`

### Container Query Contract / Output Separation

- Der Container-Contract-Strang fuer
  - `container_inventory`
  - `container_blueprint_catalog`
  - `container_state_binding`
  ist jetzt im Codepfad praktisch nachgezogen.
- Stand 2026-04-07:
  - `home_start` startet gestoppte `trion-home`-Container jetzt wirklich neu
    statt einen gestoppten Altzustand nur als "reuse" zurueckzugeben
  - `home_start` erzeugt jetzt auch im Workspace-/Chat-Pfad ein sauberes
    `container_started`-Event
  - `container_inventory` behaelt die strukturierte `container_list`-Evidence
    jetzt bis in den Output-Fallback; dadurch kippt die sichtbare Endantwort
    nicht mehr faelschlich auf "keine laufenden/gestoppten Container
    verifiziert"
  - verifiziert ueber:
    - `starte bitte den TRION Home Workspace`
    - `welche container hast du, und welcher Container sind an und welche sind aus?`
  - Ergebnis:
    - `trion-home` bleibt im Backend wirklich `running`
    - Runtime-Inventar zeigt sichtbar:
      - laufend: `trion-home`
      - gestoppt: `runtime-hardware`, `filestash`
    - `container_state_binding` faellt bei Modell-Drift jetzt sichtbar sauber
      auf Binding-/Runtime-Fallback zurueck statt unbelegte Zeit- oder
      Profildeutungen anzuzeigen
  - Nachgezogen am 2026-04-07:
    - `ConversationContainerState` ist jetzt persistent ueber
      `jarvis-admin-api`-Restarts hinweg
    - der Commander-Seeding-Pfad schreibt kanonische Docker-Voll-IDs statt
      kurzer Route-IDs
    - live verifiziert ueber
      `POST /api/commander/containers/<short-id>/trion-shell/start`
      plus API-Restart und anschliessendes Reload des Binding-State aus
      `/app/data/conversation_container_state.json`
- Stand 2026-04-06:
  - Query-Klassen werden frueh kanonisiert
  - `_container_query_policy` wird materialisiert
  - Addon-Resolver ist jetzt explizit an `query_class` gekoppelt
  - der Output-Layer erzwingt sichtbare Antwortgerueste fuer Inventory,
    Blueprint und Binding
  - ein container-spezifischer Postcheck/Safe-Fallback faengt lokale
    Modell-Drift sichtbar ab
- Lokal live geprueft gegen:
  - echten Docker-Bestand (`docker ps -a`)
  - lokalen Blueprint-Katalog aus `memory/blueprints.db`
  - lokales Ollama mit `ministral-3:3b`
- Ergebnis:
  - `Welche Container hast du gerade zur Verfuegung?`
    -> laufend vs. gestoppt sauber getrennt
  - `Welche Blueprints gibt es?`
    -> keine unberechtigte Runtime-Aussage mehr als sichtbare Endantwort
  - `Welcher Container ist gerade aktiv?`
    -> kein Diagnose-/Action-Drift mehr in der Endantwort
- Wichtige Praezisierung:
  - das kleine lokale Outputmodell driftet in Rohantworten teils weiter
  - entscheidend ist jetzt, dass diese Drift fuer den User nicht mehr sichtbar
    bleibt, weil der Container-Contract sie auf einen sauberen
    Contract-Fallback zurueckzieht
- Offener Rest:
  - `container_request`-/Home-Start-/Routing-Drift bleibt separater Folgestrang
  - breiterer End-to-End-Recheck ueber komplette Runtime-Toolwrapper bleibt
    spaeter weiter sinnvoll

### Storage Broker / Labels / Speicherpfade

- Die aktuelle Fehlerkette ist jetzt klar getrennt:
  - `parted` hat auf `/dev/sdd` die Partition `/dev/sdd1` erfolgreich angelegt
  - `mkfs` auf `/dev/sdd1` ist danach weiterhin fehlgeschlagen
  - dadurch ist `sdd1` aktuell im Teilzustand:
    - `PARTLABEL=games`
    - `LABEL=games`
    - aber noch `filesystem=""`
- Das erklaert den Live-Befund:
  - `/dev/sdd1` bleibt nach Reload sichtbar
  - es wurde nicht "etwas anderes" formatiert
  - das Filesystem wurde bisher schlicht noch nicht erfolgreich geschrieben
- Der Storage-Broker-Setup-Wizard hatte dabei einen echten Logikfehler:
  - `Format: Fehler ...` wurde nur als Text gesammelt
  - `Provisioning` und `Commander-Freigabe` liefen trotzdem weiter
  - dieser Pfad ist jetzt gefixt; ein Formatfehler bricht den Setup-Apply ab
- Die Datentraeger-UI hatte ausserdem eine inkonsistente Zielwahl:
  - direkte Aktionen verlangten bislang bei Disks mit Partitionen eine explizit ausgewaehlte Partition
  - der Setup-Wizard nahm bei genau einer brauchbaren Partition dagegen automatisch `/dev/sdd1`
  - auch dieser Unterschied ist jetzt geglaettet
- Die Label-Discovery wurde weiter gehaertet:
  - Storage-Broker nutzt jetzt nicht nur `lsblk LABEL`
  - sondern zusaetzlich `PARTLABEL`, `/dev/disk/by-partlabel` und `blkid`
  - dadurch erscheinen z. B. `games` und `Basic data partition` jetzt wieder konsistenter im Broker
- Der `Simple`-Wizard zeigte veraltete `Speicherpfade`, weil diese nicht aus der Live-Diskliste kamen, sondern aus publizierten Commander-Storage-Assets
  - dort lagen noch alte `gaming-station-config`- und `gaming-station-data`-Eintraege
  - diese toten Assets wurden inzwischen live entfernt
  - aktuell bleibt dort nur noch `sb-managed-services-containers`
- Ein zusaetzlicher Livefehler sass zwischenzeitlich im `runtime-hardware`-Service:
  - `GET /api/runtime-hardware/resources?connector=container` lief auf `500`
  - Ursache war nicht die Discovery, sondern ein OSError beim Schreiben von `last_resources.json.tmp`
  - dadurch zeigte `Simple > Neues Blueprint` zeitweise gar keine Geraete mehr
  - der Snapshot-/Cache-Write ist jetzt best effort; der Service wurde neu deployt und liefert wieder `200 OK`
- Fuer CasaOS ist der aktuelle Befund ebenfalls klarer:
  - der Storage-Broker legt bei `Container-Speicher` den Hostpfad `/data/services/containers` an
  - dieser Pfad wird an Commander publiziert, aber im Broker-/Commander-Code derzeit nicht zusaetzlich an CasaOS registriert
  - CasaOS fuehrt in `/var/lib/casaos/db/local-storage.db` aktuell nur `o_disk`, `o_merge`, `o_merge_disk`
  - die CasaOS-Livecache-Datei `local-storage.json` enthaelt derzeit nur `sdb` und `sdc`, aber nicht `sdd`
  - parallel sieht der Storage-Broker `sdd` und `sdd1` weiterhin ganz normal
- erster Praxis-Fix dafuer ist jetzt live:
  - `storage_create_service_dir(...)` legt fuer managed Servicepfade zusaetzlich einen CasaOS-sichtbaren Alias unter `/DATA/AppData/TRION/<service_name>` an
  - fuer den bestehenden Container-Speicher wurde live angelegt:
    - `/DATA/AppData/TRION/containers -> /data/services/containers`
- Offener Rest fuer diesen Block:
  - `mkfs` auf `/dev/sdd1` weiter endgueltig stabilisieren
  - danach echten Filesystem-Typ und `LABEL` auf dem Device pruefen
  - entscheiden, ob Broker-Servicepfade explizit in CasaOS sichtbar gemacht werden sollen oder bewusst Commander-only bleiben

### Eingefroren: Sunshine / Gaming / Moonlight

- Der gesamte Gaming-/Sunshine-/Moonlight-Strang ist seit 2026-04-09
  eingefroren.
- Er ist kein aktiver Open-Issues- oder Next-Steps-Block mehr.
- Historische Details bleiben ausschliesslich im Archiv:
  [[Archiv/2026-04-gaming-station/00-Archiv-Index|Archiv/2026-04-gaming-station]].

### Gaming Station Runtime (gestoppt und archiviert)

- Dieser Abschnitt bleibt nur noch als historischer Verweis erhalten.
- Der zugehoerige Arbeitszweig ist gestoppt, archiviert und seit 2026-04-09
  eingefroren.
- Keine weitere operative Arbeit, keine weiteren Tests und keine Next Steps in
  diesem Dokument.

### Marketplace / Composite Addon

- Bundle-Support kann `Blueprint + Host Companion + Paketdateien` gemeinsam tragen
- Bundle-Support kann inzwischen auch `container_addons/...` gemeinsam tragen
- Host-Companion-Dateien können über `storage-host-helper` nativ auf dem Host materialisiert werden
- dabei wurde ein echter Export-/Import-Roundtrip-Bug gefunden und behoben:
  - `export_bundle()` muss Blueprint-Daten im JSON-Modus serialisieren, sonst landen Python-Tags wie `NetworkMode` im YAML
- Bundle-Addons werden jetzt nicht mehr in den read-only Codepfad unter `/app/intelligence_modules/...` geschrieben
- stattdessen landen sie in einem Runtime-Overlay unter `/app/data/marketplace/container_addons`
- der Addon-Loader berücksichtigt dieses Overlay zusätzlich zum Repo-Stand
- der eigentliche End-to-End-Pfad `deploy -> host companion check/install -> postchecks -> start` ist jetzt der nächste größere Test offen
- dieser End-to-End-Pfad wurde inzwischen erfolgreich bis zum laufenden GitHub-deployten Container durchgezogen
- der Installer versteht jetzt zusätzlich additive Catalog-Felder wie:
  - `package_url`
  - `has_host_companion`
  - `supports_trion_addons`
- der aktive Installpfad bleibt aber bewusst `bundle_url`-zentriert
- der lokale Host-Companion-Lifecycle ist jetzt im Kern vollständig:
  - `host_packages.apt`
  - `binary_bootstrap`
  - `postchecks`
  - `check / repair / uninstall`
- diese Aktionen sind inzwischen auch ueber Commander-API und Commander-Frontend erreichbar
- eine kleine Store-Ecke bleibt dabei sichtbar:
  - `delete_blueprint()` ist Soft-Delete
  - Wiederverwendung derselben Blueprint-ID kann deshalb in SQLite an `UNIQUE` scheitern, wenn man Test-IDs nicht variiert

### TRION Shell

- GUI-Interaktionen sind besser, aber noch nicht perfekt
- echte autonome Mehrschritt-Ausführung wurde bewusst noch nicht aktiviert
- Risk-Gates sind aktuell eher leichtgewichtig als tief integriert
- der frühere WebSocket-Race im Shell-Attach-Pfad wurde entschärft:
  - `attach`/`stdin` werden nicht mehr still verworfen, wenn der Socket noch nicht `OPEN` ist
  - beim Reconnect wird der aktuell angehängte Container automatisch erneut attached

### Addons

- `addon_docs` werden inzwischen im Commander-UI angezeigt
- das Addon-System ist vorbereitet, aber noch jung
- mehr Containerprofile würden den praktischen Nutzen schnell erhöhen

### Orchestrator-Architektur / Entflechtung

- Neuer Architekturpfad dokumentiert in
  [[2026-04-07-orchestrator-architektur-refactor-plan]].
- Architektur-Audit dokumentiert in
  [[2026-04-08-orchestrator-architecture-audit-first-extraction-cut]].
- Stand 2026-04-09:
  - `core/orchestrator.py` bleibt ein echter Wartungsblocker, aber der erste
    kontrollierte Entflechtungspfad laeuft jetzt
  - der Refactor bleibt **kein** Big-Bang-Rewrite, sondern eine
    fachlich geschnittene Extraktion mit bestehendem API-/Call-Site-Verhalten
  - der erste lokale Extraktionsstrang (`Phase 1a` bis `1c`) ist umgesetzt in:
    - `core/orchestrator_domain_container_policy_utils.py`
  - der initiale Semantik-Block (`Phase 2`) ist lokal umgesetzt in:
    - `core/orchestrator_semantic_context_utils.py`
  - der anschliessende Response-Guard-/Contract-Block ist lokal umgesetzt in:
    - `core/orchestrator_response_guard_utils.py`
  - der kleine Output-Glue-Block ist lokal umgesetzt in:
    - `core/orchestrator_output_glue_utils.py`
  - der grosse Policy-Catalog-/Cron-/Policy-Runtime-Block ist lokal umgesetzt in:
    - `core/orchestrator_policy_catalog.py`
    - `core/orchestrator_cron_intent_utils.py`
    - `core/orchestrator_policy_runtime_utils.py`
  - der stateful Runtime-/Follow-up-Block ist lokal umgesetzt in:
    - `core/orchestrator_state_runtime_utils.py`
  - der Context-/Workspace-/Retrieval-Block ist lokal umgesetzt in:
    - `core/orchestrator_context_workspace_utils.py`
  - der Execution-Resolution-Block ist lokal umgesetzt in:
    - `core/orchestrator_execution_resolution_utils.py`
  - der Postprocess-/Autosave-Block ist lokal umgesetzt in:
    - `core/orchestrator_postprocess_utils.py`
  - der Compact-Context-/Guardrail-Block ist lokal umgesetzt in:
    - `core/orchestrator_compact_context_utils.py`
  - der Container-Candidate-Evidence-Block ist lokal umgesetzt in:
    - `core/orchestrator_container_candidate_utils.py`
  - der Interaction-/Response-Mode-Block ist lokal umgesetzt in:
    - `core/orchestrator_interaction_runtime_utils.py`
  - der Workspace-/Container-Event-Runtime-Block ist lokal umgesetzt in:
    - `core/orchestrator_workspace_event_runtime_utils.py`
  - der Pipeline-/Facade-Restblock ist lokal umgesetzt in:
    - `core/orchestrator_pipeline_facade_utils.py`
  - der verbleibende Class-Body-Policy-Catalog ist lokal verschlankt:
    - mechanische Nachbindung der Class-Attribute statt grossem Inline-Block
  - der API-/Lifecycle-Facade-Restblock ist lokal umgesetzt in:
    - `core/orchestrator_api_facade_utils.py`
  - fuer die Wrapper-/Facade-Ordnung gibt es jetzt zusaetzlich:
    - `core/orchestrator_modules/`
    - `api_facade.py`
    - `pipeline_facade.py`
    - `interaction_runtime.py`
    - `workspace_events.py`
    - `catalog.py`
    - `policy/`
    - `runtime/`
    - `context/`
    - `output/`
    - `execution/`
    - `postprocess.py`
    - die bisherigen Top-Level-Dateien bleiben vorerst als Compatibility-Shims
  - die Migrationsbasis fuer einen spaeteren echten Paket-Rename ist jetzt
    testseitig vorbereitet:
    - zentrale Orchestrator-Source-Resolver in `tests/_orchestrator_layout.py`
    - keine harte Bindung wichtiger Drift-/Source-Inspection-Tests mehr nur an
      `core/orchestrator.py`
  - zuletzt verifiziert mit:
    - `167 passed` fuer Source-Layout-/Drift-/Skill-Context-/Package-Policy-Pfade
    - `59 passed, 2 skipped` fuer die gezielte Modul-Regressionssuite nach
      dem Umzug unter `core/orchestrator_modules/`
    - `226 passed, 2 skipped, 9 warnings` fuer die erste grosse persistierte
      Refactor-Regression
    - `230 passed, 2 skipped, 9 warnings` fuer den aktuellen Refactor-
      Regressionslauf nach Clean-Install-/Compose-Haertung
  - persistente Report-Ablage ist jetzt eingerichtet:
    - Runner: `scripts/ops/run_orchestrator_refactor_suite.sh`
    - Reports: `artifacts/test-reports/orchestrator/`
    - letzter Lauf:
      - `2026-04-08T23-48-09Z-refactor-regression.log`
      - `2026-04-08T23-48-09Z-refactor-regression.junit.xml`
    - aktueller Lauf:
      - `2026-04-09T20-26-50Z-refactor-regression.log`
      - `2026-04-09T20-26-50Z-refactor-regression.junit.xml`
    - stabile Alias-Dateien:
      - `latest-refactor-regression.log`
      - `latest-refactor-regression.junit.xml`
  - aktuell aus dem Monolithen herausgezogen bzw. zentralisiert:
    - Domain-Route-/Gate-Policy
    - Home-Info-/Home-Start-/Binding-/Capability-Tool-Shaping
    - Container-Query-Policy-Materialisierung
    - Skill-Catalog-nahe Strategy-/Trace-/Finalization-Helfer
    - Skill-Katalog-/Addon-/Runtime-Snapshot-Kontext
    - Active-Container-Capability-Context
    - Conversation-Consistency-Guard
    - Grounding-Auto-Recovery-Kleber
    - Tool-Result-Formatierung / Tool-Card / Evidence-Merge
    - `compute_ctx_mode` / Workspace-Observation-Extraktion
    - Policy-Konstanten / Marker / Tool-Mappings
    - Cron-Intent-/Schedule-/Ack-/Tool-Normalisierungslogik
    - Tone-/Query-Budget-/Domain-/Precontrol-Steuerungsblock
    - Container-State / Pending-Container-Resolution
    - Grounding-State / Carryover / usable-grounding
    - Follow-up-Tool-Reuse inklusive state-only Fallback
    - Master-Workspace-Event-Summary / Persistenz-Kleber
    - Retrieval-Budget-Policy
    - Tool-Context-Clipping inklusive JSON-/Structured-Fail-Safes
    - Control-Tool-Decision-Sammlung
    - finale Execution-Tool-Resolution / Follow-up-Reuse / Fallback-Kette
    - archive-embedding queue / fallback
    - fact-save / assistant-autosave / grounding-gates
    - compact-context / fail-closed retrieval-build
    - effective-context guardrail / full-mode clipping
    - blueprint hint extraction / `_container_resolution` / `_container_candidates`
    - interaction/runtime helpers fuer response mode / think filtering / output-model resolution
    - keyword fallback / trigger router / requested skill extraction
    - workspace/container event build + emitter delegation
    - explicit deep/think markers / tool-name extraction
    - home-info-vs-home-start detection / skill-router / blueprint-router glue
    - context-append / failure-compact / final-cap / tool-context helpers
    - skill-prefetch / container-verify / structure-summary / thinking execution
    - class-body policy catalog binding statt grossem Inline-Attributblock
    - api-/lifecycle-facade fuer process / stream / chunking / control / memory
  - `core/orchestrator.py` liegt lokal jetzt bei `2870` statt `6161` Zeilen
  - Clean-Install-/Release-Gate wurde lokal erfolgreich durchlaufen:
    - `bash scripts/ops/trion_release_clean.sh --yes --non-interactive`
    - Live Restore `status=success`
    - Abschlussdiagnose `Status: HEALTHY`, `PASS=30`
    - aktueller Restore-Report:
      `logs/live_restore_report_20260409-202618.json`
  - dabei stack-seitig gehaertet:
    - `storage-broker` bereitet sein Named Volume per EntryPoint vor und droppt
      danach auf UID/GID `1000`
    - `jarvis-admin-api` bereitet `commander-data`, `storage-broker-data`,
      `trion_home_data`, `memory-data`, `memory` und `memory_speicher` per
      EntryPoint vor und droppt danach auf UID/GID `1000`
    - Restore-/Reset-Skripte nutzen Admin-API-`docker exec`-Schreibpfade
      explizit als `1000:1000`
    - `trion_release_clean.sh` wartet nach Service-Restart vor der Diagnose auf
      Admin-API- und Runtime-Readiness
  - verifiziert ueber die zuletzt gezielten Suites mit:
    - `161 passed` fuer Workspace-/Emitter-/Event-Drift-Pfade
    - `156 passed` fuer Interaction-/Routing-/Skill-Context-Pfade
    - `215 passed, 5 skipped` fuer Pipeline-/Context-/Budget-/Runtime-Safeguard-Pfade
    - `100 passed, 2 skipped` fuer Class-Attr-/Import-/Runtime-Grundpfade
    - `116 passed, 2 skipped` fuer API-/Control-/Runtime-Grundpfade
- weiter gueltige Leitplanken:
  - keine Produktfeatures mit dem Refactor vermischen
  - vor jedem weiteren Schnitt Pinning-Regressionen fuer Container-/Control-/Output-
    Pfade sichern

## Empfohlene nächste Schritte

1. Storage-Broker-Repartitionierung und `mkfs` weiter haerten
   - `udev`-/Kernel-Nachlauf beim Repartitionieren
   - `mkfs`-Retry/Busy-State
   - generische `LABEL`/`PARTLABEL`-Anzeige konsistent machen
   - CasaOS gegen den aktuellen Storage-Zustand gegenpruefen:
     - `GET /v2/local_storage/merge` liefert weiter `503`, weil `EnableMergerFS=false`
     - CasaOS fuehrt aktuell `sdb` und `sdc`, aber nicht `sdd`
     - Broker-Servicepfade wie `/data/services/containers` erscheinen dort aktuell nicht automatisch
2. `runtime-hardware`-Folgepolish weiterfuehren
   - sprechende Storage-/Block-Device-Namen
   - weitere UI-/Preset-Haertung
   - nicht-Block-Hardware-Intents (`input`/`usb`/`device`) gegen spaetere Re-Deploys stabilisieren
   - pruefen, ob die `Simple`-Auswahl dort staerkere stabile Schluessel statt roher Hostknoten braucht
3. den neuesten GitHub-/Marketplace-Paketstand erneut importieren, damit Host-Companion- und Paket-Haertungen auch im Runtime-Paketstore liegen
4. weitere Containerprofile ergänzen, z. B. Datenbank-, MCP-, Web- und Service-Container
5. Shell-Policy weiter schärfen, vor allem für GUI- und Write-Aktionen
6. TRION-Multistep-Loop als Chat-first-Aufgabenmodus planen und umsetzen
   - Implementationsplan:
     [[2026-04-09-trion-multistep-loop-implementationsplan]]
   - zuerst im Chatfenster: planen, ausfuehren, Zwischenantwort, reflektieren,
     weiter machen oder stoppen
   - Planungsmodus als sichtbarer Aufgabenfaden
   - Shell-Mikro-Loops erst spaeter, wenn Chat-Loop und Gates stabil sind
7. bei Bedarf Blueprint-seitige Addon-Registrierung ergänzen
8. Commander-UI optional klarer anzeigen lassen, wenn ein Service `stopped and preserved` ist
9. den trägen Tabwechsel / verspätete Panel-Updates im Commander gezielt untersuchen
10. Architekturpfad fuer `core/orchestrator.py` nach Phase `1`, Semantik-Block
   Response-Guard-Block und Output-Glue-Block weiterfuehren
   - naechster Block: groessere stateful/runtime-nahe Pfade
   - stateful Streaming-/Sync-/Lifecycle-Pfade weiter bewusst spaeter anfassen

## Mögliche spätere Ausbaustufen

- eigener `shell control model`-Schalter
- user-erweiterbare Addon-Sammlungen pro Blueprint
- stärkere Recovery-/Verification-Strategien
- feinere Storage-/Commander-/TRION-Integration auf Asset-Ebene
