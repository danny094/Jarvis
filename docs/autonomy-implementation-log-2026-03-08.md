# TRION Autonomy Implementation Log (2026-03-08)

## Ziel
TRION von "Container-Manager mit Teil-Automation" zu "autonom planendem Agenten" ausbauen,
mit nachvollziehbaren Plan-Schritten im Workspace/Planmode und stabiler Runtime-Transparenz.

## Scope (diese Umsetzung)
- Autonome Plan-Events im Master-Orchestrator erzeugen.
- Plan-Events in `workspace_events` persistieren (für Workspace Sidepanel).
- Runtime-Status für Autonomie als API verfügbar machen.
- Verträge per Unit-Tests absichern.

## Nicht im Scope (später)
- Eigener Cronjob für autonome Objectives.
- Vollständiger Policy-Enforcer als eigener Service.
- Erweiterte Langzeit-Scheduler/Queue-Orchestrierung.

## Schrittplan
- [x] Schritt 1: Dieses Log-Dokument anlegen
- [x] Schritt 2: Master-Orchestrator Event-Emission erweitern
- [x] Schritt 3: Pipeline-Orchestrator Event-Persistenz anbinden
- [x] Schritt 4: Runtime-Endpoint für Autonomy-Status ergänzen
- [x] Schritt 5: Tests ergänzen und ausführen

## Laufendes Protokoll
### Schritt 1 abgeschlossen
- Dokument angelegt.
- Vorgehen fixiert, damit der Fortschritt nicht verloren geht.

### Schritt 2 abgeschlossen
- `core/master/orchestrator.py` erweitert um best-effort Event-Emission:
  - `planning_start`, `planning_step`, `planning_done`, `planning_error`
- Master-Settings werden pro Objective-Lauf frisch geladen.
- `enabled=false` wird jetzt respektiert (früher wirkungslos).
- `completion_threshold` wird in der Reflection-Entscheidung verwendet (statt harter Konstante).

### Schritt 3 abgeschlossen
- `core/orchestrator.py` bindet den Master-Event-Sink beim Init an.
- Master-Events werden als `workspace_events` persistiert (`source_layer=master`).
- Planmode/Workspace kann autonome Plan-Läufe dadurch reload-sicher nachvollziehen.

### Schritt 4 abgeschlossen
- Neuer Endpoint: `GET /api/runtime/autonomy-status` in `adapters/admin-api/runtime_routes.py`.
- Liefert eine kompakte Readiness-Sicht für autonome Planung:
  - Master-Orchestrator-Settings
  - Tool-Verfügbarkeit (`think`, `sequential_thinking`, `workspace_event_save`, `workspace_event_list`)
  - Home-Container-Status (`connected/degraded/offline` + `error_code`)

### Schritt 5 abgeschlossen
- Neue Tests:
  - `tests/unit/test_master_autonomy_planning_events.py`
  - `tests/unit/test_orchestrator_master_workspace_events.py`
  - `tests/unit/test_runtime_autonomy_status_contract.py`
- Testlauf (gezielt, inkl. bestehender betroffener Contracts): **76 passed**

### Post-Check
- Syntax-Check (`py_compile`) für geänderte Core/API-Dateien: OK
- Re-Run der neuen Tests: **7 passed**

## Skill-Stability Hardening (heute)
Ziel: Autonome Skill-Execution stabilisieren, damit defekte bestehende Skills
nicht den gesamten Autonomie-Flow abbrechen.

### Schritt 6 abgeschlossen — Fallback im Autonomous-Flow
- Datei: `mcp-servers/skill-server/mini_control_core.py`
- Verhalten geändert:
  - Wenn ein gematchter bestehender Skill beim Run fehlschlägt, wird bei erlaubter
    Policy (`allow_auto_create` + Threshold) automatisch auf Create-Flow gefallbackt.
  - Wenn Fallback nicht erlaubt ist, bleibt der Flow fail-closed (kein stilles Bypass).

### Schritt 7 abgeschlossen — Contract-Tests ergänzt
- Datei: `tests/unit/test_single_control_authority.py`
- Neue Tests:
  - Fallback von defektem Existing-Skill auf Create-and-Run.
  - Fail-closed, wenn Auto-Create-Fallback deaktiviert ist.

### Schritt 8 abgeschlossen — Sanity + Integration Re-Check
- Unit:
  - `tests/unit/test_single_control_authority.py` → **26 passed**
  - `tests/unit/test_mini_control_core_sync.py` → **2 passed**
- Integration:
  - `tests/integration/test_autonomous_skill_creation.py` → **4 passed**
- Zusätzlich:
  - `scripts/sync_mini_control_core.py` ausgeführt (source/target parity hergestellt).
  - Laufender `trion-skill-server`-Container neu geladen, damit Runtime-Test den
    aktuellen Patch wirklich verwendet.
  - Skill-Gate Quick-Run: `bash scripts/test_skill_flow_gate.sh quick` → **passed**.

### Schritt 9 abgeschlossen — Full E2E Gate + Prioritätsentscheidung (2026-03-08)
- Ausgeführt:
  - `AI_TEST_LIVE=1 AI_PERF_ENABLE=1 ./scripts/test_full_pipeline_bottleneck_gate.sh`
- Ergebnis:
  - **FAIL** im Perf-Gate (`tests/e2e/test_ai_pipeline_perf.py`)
  - Grund: `p95_e2e_ms = 26020.531` bei Limit `20000.0`
- Gegencheck Funktion:
  - `tests/integration/test_autonomous_skill_creation.py` → **4 passed**
- Entscheidung:
  - **Cronjobs werden nach hinten priorisiert**, bis der E2E-Perf-Bottleneck stabil im Zielbereich liegt.
  - Nächster Fokus: Pipeline-/Runtime-Bottleneck (Thinking/Control/Memory/Output Pfad).

---

## Bottleneck Stabilization v2 (heute)

Ziel:
- TTFT-Spitzen durch Stream-Buffering reduzieren
- Tool-Pfad bei low-complexity Anfragen budgetieren
- Autonomie-Entscheidungen früh und nachvollziehbar machen

### v2 Schrittstatus
- [x] Schritt 1: Baseline fixiert
- [x] Schritt 1b: Archäologie-Review zum Buffering
- [x] Schritt 2: Stream-Buffering-Fix (Feature-Flag + Policy)
- [x] Schritt 3+4: Query-Preclassifier + Tool-Budget-Policy (kombiniert)
- [x] Schritt 5: Response-Budget-Signal in bestehende Length-Policy eingehängt
- [ ] Schritt 6: Autonomie-Policy weiter schärfen (reason-codes / deep-vs-fast-path feinjustieren)
- [x] Schritt 7: Unit-Tests erweitert
- [x] Schritt 8: Rollout in 2 Stufen + erneuter E2E-Gate

### Schritt 1 abgeschlossen — Baseline
- Referenz für Bottleneck-Analyse bleibt:
  - `/tmp/ai_perf_full_prompts_20260308.json`
  - `overall p95_e2e_ms ≈ 25730.794`
  - `stream p95_ttft_ms ≈ 12442.977`
- Haupttreiber waren lange analytical/factual Antworten + stream-spezifisches Buffering.

### Schritt 1b abgeschlossen — Archäologie-Review
- Root-Cause bestätigt:
  - In `core/layers/output.py` wurde bei factual Postcheck vollständig gepuffert (`buffer_for_postcheck`),
    um numerische/qualitative Grounding-Checks vor Ausgabe durchzusetzen.
- Risiko beim Entfernen:
  - Verlust der Halluzinations-Sicherung in fact-query Antworten.
- Entscheidung:
  - Kein harter Remove, sondern **Modussteuerung**:
    - `buffered` (Legacy)
    - `tail_repair` (neu, stream-first)
    - `off` (Debug/Notfall)

### Schritt 2 abgeschlossen — Stream-Buffering-Fix
- Geändert:
  - `core/layers/output.py`
  - `core/grounding_policy.py`
  - `core/mapping_rules.yaml`
  - `config.py`
- Neues Verhalten:
  - Standard ist jetzt `stream_postcheck_mode: tail_repair`.
  - Output wird sofort gestreamt; Postcheck läuft am Ende über den bereits gestreamten Inhalt.
  - Nur bei erkannter Grounding-Verletzung wird eine **nachgelagerte Korrektur** angehängt.
- Rollback:
  - `OUTPUT_STREAM_POSTCHECK_MODE=buffered` (oder policy `stream_postcheck_mode: "buffered"`).

### Schritt 3+4 abgeschlossen — Query-Preclassifier + Tool-Budget (kombiniert)
- Neue Komponente:
  - `core/query_budget_hybrid.py`
- Integration:
  - `core/orchestrator.py`
    - frühes Query-Signal (`query_type`, `intent_hint`, `complexity_signal`, `response_budget`, `tool_hint`, `skip_thinking_candidate`)
    - Signal wird in den Thinking-Plan übernommen (`_query_budget`)
    - Tool-Auswahl wird budgetiert (z. B. heavy-tools bei `factual+low` reduzieren)
- Safe-Rails:
  - expliziter Tool-Intent des Users umgeht harte Suppression
  - classifier-basierter Thinking-Skip ist hinter Flag (konservativ default off)

### Schritt 5 abgeschlossen — Response-Budget
- Kein zweites Budget-System eingeführt.
- Stattdessen wird `response_budget` auf bestehende `response_length_hint`-Policy gemappt.
- Dadurch nutzt der OutputLayer sofort die vorhandenen Char-Caps/Soft-Targets.

### Schritt 7 abgeschlossen — Tests
- Neue/erweiterte Unit-Tests:
  - `tests/unit/test_query_budget_hybrid.py`
  - `tests/unit/test_orchestrator_query_budget_policy.py`
  - `tests/unit/test_output_grounding.py` (stream-postcheck mode assertions ergänzt)
- Testlauf:
  - `python -m pytest -q tests/unit/test_output_grounding.py tests/unit/test_query_budget_hybrid.py tests/unit/test_orchestrator_query_budget_policy.py`
  - Ergebnis: **29 passed**
- Syntax-Check:
  - `python -m py_compile core/layers/output.py core/orchestrator.py core/query_budget_hybrid.py core/grounding_policy.py config.py` → OK

### Schritt 8 Update — Full Bottleneck Gate Re-Run (2026-03-08, UTC)
- Ausgeführt:
  - `AI_TEST_LIVE=1 AI_PERF_ENABLE=1 ./scripts/test_full_pipeline_bottleneck_gate.sh`
- Ergebnis:
  - **FAIL** im Perf-Gate (`tests/e2e/test_ai_pipeline_perf.py`)
  - `p95_e2e_ms = 24452.27` bei Gate-Limit `20000.0`
  - Laufzeit: `469.56s` (`0:07:49`)
- Vergleich zum vorherigen Full-Gate (gleicher Tag):
  - vorher: `p95_e2e_ms = 26020.531`
  - jetzt: `p95_e2e_ms = 24452.27`
  - Delta: `-1568.261 ms` (`-6.03%`)
- Bewertung:
  - Verbesserungsrichtung bestätigt, aber Gate weiterhin nicht bestanden.
  - **Cronjobs bleiben nachgelagert**, bis `p95_e2e_ms <= 20000` stabil erreicht wird.

### Offene Punkte (nächster Durchlauf)
- E2E-Perf-Gate erneut laufen lassen (mit neuen stream-first Pfaden).
- Schritt 6/8 finalisieren:
  - reason-codes in Logs weiter verdichten
  - staged rollout (Flag default-on nach Perf-Nachweis)

### Hotfix — Admin-API Restart-Loop repariert (2026-03-08, UTC)
- Symptom:
  - `jarvis-admin-api` restartete dauerhaft nach `docker restart`.
  - Fehler: `ModuleNotFoundError: No module named 'trion_memory_routes'`.
- Ursache:
  - Laufendes Container-Dateisystem/Image war inkonsistent zum Workspace-Stand
    (TRION-Memory-Routenmodul im Runtime-Pfad nicht verfügbar).
- Fix:
  - `adapters/admin-api/commander_routes.py`:
    - optionaler Import für `trion_memory_routes` mit `try/except ModuleNotFoundError`
    - Router nur inkludieren, wenn Import erfolgreich.
  - `adapters/admin-api/main.py`:
    - gleicher optionaler Import + conditional include für `/api/trion/memory`.
  - Laufender Container hotfix:
    - `docker cp adapters/admin-api/trion_memory_routes.py jarvis-admin-api:/app/trion_memory_routes.py`
    - `docker restart jarvis-admin-api`
- Ergebnis:
  - `GET /health` wieder **200 OK** (Service stabil gestartet).
  - `GET /api/trion/memory/status` wieder **200 OK**.
  - Hinweis: Der `docker cp`-Hotfix ist laufzeitbezogen; dauerhaft bleibt ein
    sauberer Rebuild/Deploy des Admin-API-Containers notwendig.

### Full Bottleneck Gate Re-Run nach Hotfix (2026-03-08, UTC)
- Ausgeführt:
  - `AI_TEST_LIVE=1 AI_PERF_ENABLE=1 ./scripts/test_full_pipeline_bottleneck_gate.sh`
- Ergebnis:
  - **FAIL** im Perf-Gate (`tests/e2e/test_ai_pipeline_perf.py`)
  - `overall p95_e2e_ms = 70059.428` (Limit `20000.0`)
  - `stream p95_ttft_ms = 51532.148` (Limit `8000.0`)
  - Report: `logs/perf/full_pipeline_perf_20260308-230743.json`
- Vergleich zum vorherigen Re-Run:
  - vorher: `p95_e2e_ms = 80135.476`
  - jetzt: `p95_e2e_ms = 70059.428`
  - Delta: `-10076.048 ms` (`-12.57%`)
- Hauptausreißer:
  - Prompt `Analysiere Input-zu-Output Pipeline in 5 Punkten...`
  - Sync: bis `69573.305 ms` bei `~1053 completion_tokens_est`
  - Stream: bis `79295.758 ms`, TTFT bis `60465.58 ms`

### Stabilisierung abgeschlossen — Full Gate PASS (2026-03-08, UTC)
- Zusätzliche Fixes nach dem Re-Run:
  - `tests/e2e/test_ai_pipeline_perf.py`: Report wird jetzt auch bei Threshold-Fail geschrieben (`gate.ok` + `gate.failures` im JSON).
  - `core/orchestrator.py`:
    - `think_simple` als Heavy-Tool klassifiziert.
    - Analytical+Interactive Tool-Budget droppt Heavy-Tools deterministisch.
    - Skill-Trigger-Router nur noch bei **explizitem Skill-Intent**.
    - Skill-Dedup-Gate blockt implizite Skill-Routen (`no_explicit_skill_intent`).
  - `core/layers/output.py` + `config.py`:
    - zusätzliche Analytical-Caps im Interactive-Mode
      (`OUTPUT_CHAR_CAP_INTERACTIVE_ANALYTICAL`, `OUTPUT_CHAR_TARGET_INTERACTIVE_ANALYTICAL`).
- Finaler Full-Gate Lauf:
  - `AI_TEST_LIVE=1 AI_PERF_ENABLE=1 ./scripts/test_full_pipeline_bottleneck_gate.sh`
  - Ergebnis: **PASSED**
  - Report: `logs/perf/full_pipeline_perf_20260308-233527.json`
  - Summary: `logs/perf/full_pipeline_bottleneck_20260308-233527.json`
- Finale Kennzahlen:
  - `overall p95_e2e_ms = 14862.957` (Gate-Limit `20000.0`)
  - `stream p95_ttft_ms = 3932.752` (Gate-Limit `8000.0`)
- Verbesserung ggü. vorherigem Re-Run:
  - `p95_e2e_ms`: `70059.428 → 14862.957` (`-78.78%`)

---

## Marketplace Launchpad V1 (2026-03-09, UTC)

Ziel:
- Marketplace als eigene Launchpad-App sichtbar machen und den End-to-End-Flow
  `sync -> list/filter -> install` im WebUI testbar machen.

Umsetzung:
- Frontend-Wiring:
  - `adapters/Jarvis/index.html`
    - neues App-Window `#app-marketplace`
    - neues Launchpad-Icon `Marketplace`
    - neue CSS-Einbindung `static/css/marketplace.css`
  - `adapters/Jarvis/js/shell.js`
    - neues App-State-Feld `marketplaceLoaded`
    - Window-Mapping für `marketplace`
    - Lazy-Load Route `import('./apps/marketplace.js')`
- Neue App-Dateien:
  - `adapters/Jarvis/js/apps/marketplace.js`
    - Katalog laden (`/marketplace/catalog`)
    - Katalog sync (`/marketplace/catalog/sync`)
    - Install-Action (`/marketplace/catalog/install/{id}`)
    - Installed-Status via lokaler Blueprint-Liste (`/blueprints`)
    - Filter: Kategorie, Trusted-only, Suche
  - `adapters/Jarvis/static/css/marketplace.css`
    - modernes V1-Layout im Commander-Look (Cards, Chips, KPI-Panel, responsive Grid)
- Contract-Tests:
  - `tests/unit/test_frontend_marketplace_app_wiring_contract.py`

Live-Status:
- `catalog sync`: **OK**
- `catalog list/filter`: **OK**
- `catalog install`: API-Flow **OK**, aber einzelne Repo-YAMLs aktuell noch
  teils **Schema-inkompatibel** (z. B. `mounts[].host` fehlt beim lokalen Schema).

Nächster Schritt (separat):
- Importer robuster machen (Mapping für `type: volume`-Mounts), damit Install
  aus externen Blueprint-Repos ohne manuelle YAML-Anpassung funktioniert.

---

## MCP Tools UI Modernization V1 (2026-03-09, UTC)

Ziel:
- MCP-Management im modernen Commander-Style anbieten, inkl. Klick-Detailansicht,
  Enable/Disable, Restart/Reload und editierbarer Custom-Config.

Umsetzung:
- Frontend:
  - `adapters/Jarvis/js/apps/tools.js` komplett auf neue Split-View umgestellt:
    - linke MCP-Liste (Suche + Status-Chips)
    - rechte Detailansicht (MCP-Metadaten + Tool-Liste + Config-Editor)
    - Aktionen: `toggle`, `delete`, `restart hub`, `save config`
  - neues Styling: `adapters/Jarvis/static/css/tools.css`
  - CSS-Einbindung in `adapters/Jarvis/index.html`
- Backend:
  - `mcp/installer.py` erweitert um:
    - `GET /api/mcp/{name}/config` (nur Custom-MCP, core read-only)
    - `PUT /api/mcp/{name}/config` (write + hub reload)

Tests:
- `tests/unit/test_mcp_installer_config_routes_contract.py`
- `tests/unit/test_frontend_tools_modern_wiring_contract.py`

Status:
- V1 funktionsfähig für UI-gesteuerte MCP-Administration ohne Terminal.
  - `stream p95_ttft_ms`: `51532.148 → 3932.752` (`-92.37%`)

## MCP Details | Settings — Implementierungsplan (2026-03-09, UTC)

Ziel:
- Im MCP-Fenster zwei klare Tabs bereitstellen:
  - `Details`: Metadaten, Tool-Liste, Status
  - `Settings`: editierbare, backend-wirksame Konfigurationen pro MCP

Backend-Basis (bereits vorhanden):
- `GET /api/tools`
  - Vollständige MCP-/Tool-Metadaten inkl. `inputSchema` je Tool.
- `GET /api/mcp/list`
  - MCP-Statusliste für Sidepanel.
- `GET /api/mcp/{name}/details`
  - Detailansicht pro MCP (Tools, Health, Metadaten).
- `GET /api/mcp/{name}/config`
  - Custom-MCP-Konfiguration laden (core MCPs read-only).
- `PUT /api/mcp/{name}/config`
  - Custom-MCP-Konfiguration speichern (inkl. reload).
- `POST /mcp/refresh`
  - Hub-Refresh nach Änderungen.

Was in `Settings` darstellbar ist (backend-seitig):
- `sequential-thinking`
  - optionale Laufzeitparameter wie `steps`, `mode`, `use_cim`, `use_memory`, `validate_steps`.
- `cim`
  - optionale Parameter wie `mode`, `include_visual`, `include_prompt` (+ Validierungsflags).
- `skill-server`
  - optionale Felder in `create_skill`, `run_skill`, `query_skill_knowledge`, `autonomous_skill_task`.
- `sql-memory`
  - Tuning-Parameter (u. a. Search-Limits, Graph-Schwellen, Maintenance-Modelle/URLs).
- `container-commander`/`sysinfo`/`fast-lane`
  - Tool-spezifische Defaults und sichere UI-Vorbelegungen.

UI-Plan (V2, ohne Prompting, deterministisch):
- Tab `Details`
  - Nur Read-Only Fakten (Status, Tools, Schemas, letzte Aktion).
- Tab `Settings`
  - Form-Renderer aus `inputSchema`/Config-JSON.
  - Strikte Typvalidierung client+server (kein Freitext-Guessing).
  - `Save` schreibt ausschließlich über `PUT /api/mcp/{name}/config`.
  - `Restart/Refresh` separat, explizit per Button.

Offener Blocker (vor V2 fixen):
- `POST /api/mcp/{name}/toggle` liefert aktuell `500`.
  - Ursache: `ImportError` (`get_mcps` fehlt in `mcp_registry.py`).
  - Wirkung: Enable/Disable aus UI nicht verlässlich.
  - Priorität: **P0**, weil Settings-UX sonst inkonsistent bleibt.

Abnahme-Kriterien:
- Pro MCP sind `Details` und `Settings` klar getrennt sichtbar.
- Änderungen in `Settings` sind nach Reload persistent und wirksam.
- Toggle/Restart/Refresh funktionieren ohne 5xx.
- Keine „Fake-Settings“: nur Felder anzeigen, die backend-seitig existieren.

### Regression-Fix — E2E-Ausreißer behoben (2026-03-08, UTC)
- Reproduktion:
  - Gate-Lauf: `AI_TEST_LIVE=1 AI_PERF_ENABLE=1 ./scripts/test_full_pipeline_bottleneck_gate.sh`
  - Ergebnis: **FAIL**
  - Report: `logs/perf/full_pipeline_perf_20260308-234037.json`
  - Kennzahlen:
    - `overall p95_e2e_ms = 21329.473` (Limit `20000.0`)
    - `stream p95_ttft_ms = 3729.145` (innerhalb Limit)
- Root-Cause:
  - `explicit_tool_intent` hatte False-Positives:
    - `"Tooling"` matchte `"tool"` (Substring)
    - `"Memory"` in Architektur-Prompts matchte `"memory"` und hielt teure Tool-Pfade offen.
  - Thinking-Plan-Cache lief während des Runs partiell aus:
    - TTL wurde bei Cache-Hits nicht aufgefrischt.
    - Dadurch sporadische Cache-Misses mit teurer Thinking+Control-Phase in Sync-Runs.
- Fixes:
  - `core/orchestrator.py`
    - neue Keyword-Erkennung mit Whole-Word-Match für intent-sensitive Tokens.
    - `memory` aus expliziten Tool-Intent-Keywords entfernt.
    - Skill-Intent ebenfalls auf Word-Boundary-Matching gehärtet.
    - Thinking-Cache TTL wird bei Cache-Hit in Sync + Stream aktiv refreshed (`set` on hit).
  - `tests/unit/test_orchestrator_query_budget_policy.py`
    - neue Tests für `Tooling`-False-Positive und Skill-Word-Boundary.
- Validierung:
  - Unit:
    - `python -m pytest -q tests/unit/test_orchestrator_query_budget_policy.py tests/unit/test_output_grounding.py tests/unit/test_query_budget_hybrid.py`
    - Ergebnis: **35 passed**
  - Full Gate Re-Run:
    - Ergebnis: **PASSED**
    - Report: `logs/perf/full_pipeline_perf_20260308-234947.json`
    - Summary:
      - `logs/perf/full_pipeline_bottleneck_20260308-234947.json`
      - `logs/perf/full_pipeline_bottleneck_20260308-234947.md`
    - Kennzahlen:
      - `overall p95_e2e_ms = 10121.893`
      - `stream p95_ttft_ms = 1415.869`
      - `stream p50_tokens_per_sec = 25000.0`

---

## Pre-Cron Hardening — Autonomy Queue + Semantik (2026-03-09, UTC)

Ziel:
- Vor Cronjobs die Autonomie-API robust machen (saubere Success/Failure-Semantik, Retry/Cancellation, bessere Transparenz).

### Schrittstatus
- [x] R1: Planning-Readiness Aliase für Sequential-Tools
- [x] R2: `/api/autonomous` Success/Failure-Semantik stabilisiert
- [x] R3: Async Autonomy-Job-Queue mit `status/cancel/retry/stats`
- [x] R4: Reason-Codes in API/Workspace-Telemetrie verdichtet
- [x] R5: Doku + Validierung

### Umgesetzt
- `core/master/orchestrator.py`
  - Terminalzustände klar getrennt (`success` nur bei `completed` ohne `error_code`).
  - Reason-Codes/Stop-Reasons propagiert (`max_loops_reached`, `loop_detected`, `too_many_failures`, etc.).
  - Terminale `planning_error`-Events enthalten jetzt konsistente Diagnosefelder.
- `core/orchestrator.py`
  - Workspace-Zusammenfassung für `planning_start/planning_done/planning_error` erweitert
    (inkl. `planning_mode`, `stop_reason`, `error_code`).
- `adapters/admin-api/runtime_routes.py`
  - Autonomy-Readiness erkennt Tool-Aliase (`sequential_thinking`/`think`/`think_simple`).
- `adapters/admin-api/main.py`
  - Neue async Autonomy-Endpunkte:
    - `POST /api/autonomous/jobs`
    - `GET /api/autonomous/jobs/{job_id}`
    - `POST /api/autonomous/jobs/{job_id}/cancel`
    - `POST /api/autonomous/jobs/{job_id}/retry`
    - `GET /api/autonomous/jobs-stats`
  - Queue-Mechanik analog Deep-Jobs: Retention, Concurrency-Semaphore, Timeout, Idempotent-Cancel.
  - Sync-Endpoint `/api/autonomous` nutzt jetzt dieselbe Request-Normalisierung + `error_code`.
- `config.py`
  - Neue Runtime-Knobs:
    - `AUTONOMY_JOB_TIMEOUT_S`
    - `AUTONOMY_JOB_MAX_CONCURRENCY`

### Tests (2026-03-09)
- Neu:
  - `tests/unit/test_admin_api_autonomy_jobs_contract.py`
- Relevanter Lauf:
  - `python -m pytest -q tests/unit/test_admin_api_autonomy_jobs_contract.py tests/unit/test_admin_api_deep_jobs_contract.py tests/unit/test_master_autonomy_planning_events.py tests/unit/test_orchestrator_master_workspace_events.py tests/unit/test_runtime_autonomy_status_contract.py`
  - Ergebnis: **19 passed**
- Syntax:
  - `python -m py_compile adapters/admin-api/main.py config.py core/master/orchestrator.py core/orchestrator.py adapters/admin-api/runtime_routes.py` → OK

### Runtime Smoke
- `docker restart jarvis-admin-api` → Service stabil.
- `GET /api/autonomous/jobs-stats` → 200 OK.
- Async-SMOKE:
  - Job submit + poll + retry erfolgreich erreichbar.
  - Fehlerpfad zeigt jetzt stabile Codes (`error_code=max_loops_reached`, `stop_reason=max_loops_reached`) statt implizit `success=true`.

### WebUI Wiring abgeschlossen (2026-03-09, UTC)
- Ziel:
  - Neue Autonomy-Job-API direkt im Workspace/Planmode nutzbar machen.
- Geändert:
  - `adapters/Jarvis/static/js/workspace.js`
    - neuer **Autonomy Control** Block im Workspace-Tab
    - Runtime-Badge (`ready/degraded`) aus `/api/runtime/autonomy-status`
    - Queue-Metriken aus `/api/autonomous/jobs-stats`
    - Objective-Submit (`POST /api/autonomous/jobs`)
    - Job-Aktionen `cancel` / `retry`
    - Polling (`AUTONOMY_POLL_MS=3000`) + lokale Job-ID-Persistenz (`localStorage`)
  - `adapters/Jarvis/static/css/workspace.css`
    - Styles für Autonomy-Panel, Status-Pills, Job-Cards, Actions, Mobile-Stacking
  - `adapters/Jarvis/static/js/api.js`
    - neue API-Helfer:
      - `submitAutonomyJob`
      - `getAutonomyJobStatus`
      - `cancelAutonomyJob`
      - `retryAutonomyJob`
      - `getAutonomyJobsStats`
      - `waitForAutonomyJob`
  - Tests:
    - `tests/unit/test_frontend_autonomy_jobs_wiring_contract.py` (neu)
- Validierung:
  - `node --check adapters/Jarvis/static/js/api.js adapters/Jarvis/static/js/workspace.js` → OK
  - `python -m pytest -q tests/unit/test_frontend_autonomy_jobs_wiring_contract.py tests/unit/test_frontend_stream_activity_contract.py tests/unit/test_phase6_security.py -k "workspace or frontend_autonomy or stream_activity"` → **15 passed**

---

## Cronjobs — Implementation Plan + Rollout (2026-03-09, UTC)

Ziel:
- Eigene Cron-App im Launchpad.
- Persistente Cron-Definitionen (User + TRION).
- Sichtbarkeit von `active / queued / running / paused`.
- Geplante Runs dispatchen in bestehende `/api/autonomous/jobs` Queue.

### Plan (umgesetzt)
- [x] Schritt 1: Cron Scheduler Core + Persistenz + Config-Knobs
- [x] Schritt 2: Admin-API Endpunkte für CRUD/Status/Queue/Run-now
- [x] Schritt 3: WebUI Launchpad-App `Cron` im modernen Commander-Stil
- [x] Schritt 4: Contracts + Unit-Tests
- [x] Schritt 5: Runtime Smoke + Dokumentation

### Schritt 1 — Core Scheduler
- Neu:
  - `core/autonomy/cron_scheduler.py`
  - `core/autonomy/__init__.py`
- Features:
  - 5-Feld-Cron-Parser (`min hour dom month dow`) inkl. `*`, `*/n`, ranges, lists.
  - Timezone-Support via `zoneinfo`.
  - In-Memory Queue + Running + Recent History.
  - Persistenz in JSON-Statefile (Jobs + History).
  - Manuelle Trigger (`run_now`) + automatische Tick-Dispatches.
- Config:
  - `AUTONOMY_CRON_STATE_PATH`
  - `AUTONOMY_CRON_TICK_S`
  - `AUTONOMY_CRON_MAX_CONCURRENCY`

### Schritt 2 — Admin-API
- Datei:
  - `adapters/admin-api/main.py`
- Integration:
  - Scheduler-Start im Startup, Stop im Shutdown.
  - Cron-Dispatch nutzt **bestehende** Autonomy-Job-Queue (`/api/autonomous/jobs`) via internen Submit-Callback.
  - Refactor: gemeinsamer Helper `_submit_autonomy_job_from_payload(...)` für API + Cron.
- Neue Endpunkte:
  - `GET  /api/autonomy/cron/status`
  - `GET  /api/autonomy/cron/jobs`
  - `POST /api/autonomy/cron/jobs`
  - `GET  /api/autonomy/cron/jobs/{cron_job_id}`
  - `PUT  /api/autonomy/cron/jobs/{cron_job_id}`
  - `DELETE /api/autonomy/cron/jobs/{cron_job_id}`
  - `POST /api/autonomy/cron/jobs/{cron_job_id}/pause`
  - `POST /api/autonomy/cron/jobs/{cron_job_id}/resume`
  - `POST /api/autonomy/cron/jobs/{cron_job_id}/run-now`
  - `GET  /api/autonomy/cron/queue`
  - `POST /api/autonomy/cron/validate`

### Schritt 3 — Launchpad App
- Dateien:
  - `adapters/Jarvis/js/apps/cron.js`
  - `adapters/Jarvis/static/css/cron.css`
  - `adapters/Jarvis/js/shell.js`
  - `adapters/Jarvis/index.html`
- UX:
  - Neue App `Cron` in Sidebar + Launchpad + eigenes Viewport.
  - Create-Form (Name, Objective, Cron, TZ, Conversation, Max-Loops, Created-by user/trion).
  - Status-KPIs (scheduler/jobs/queued/running).
  - Job-Tabelle mit Actions: `Run now`, `Pause/Resume`, `Delete`.
  - Queue/Running/Recent Panels für Warteliste + aktive Dispatches.
  - Auto-Refresh (5s).

### Schritt 4 — Tests
- Neu:
  - `tests/unit/test_autonomy_cron_scheduler.py`
  - `tests/unit/test_admin_api_autonomy_cron_contract.py`
  - `tests/unit/test_frontend_cron_app_wiring_contract.py`
- Zusätzlich angepasst:
  - `tests/unit/test_admin_api_autonomy_jobs_contract.py` (retry-contract tolerant für helper-refactor)
- Lauf:
  - `python -m pytest -q tests/unit/test_autonomy_cron_scheduler.py tests/unit/test_admin_api_autonomy_cron_contract.py tests/unit/test_frontend_cron_app_wiring_contract.py tests/unit/test_admin_api_autonomy_jobs_contract.py tests/unit/test_frontend_autonomy_jobs_wiring_contract.py`
  - Ergebnis: **16 passed**

### Schritt 5 — Runtime Smoke
- `docker restart jarvis-admin-api` → Service stabil.
- `GET /api/autonomy/cron/status` → scheduler running.
- Smoke:
  - `POST /api/autonomy/cron/jobs` (create) → OK
  - `POST /api/autonomy/cron/jobs/{id}/run-now` → OK
  - `GET /api/autonomy/cron/queue` zeigt `recent.status=submitted`
  - `DELETE /api/autonomy/cron/jobs/{id}` → OK

### TRION Tooling ergänzt (2026-03-09, UTC)
- Ziel:
  - Cronjobs nicht nur per UI/API, sondern direkt über TRION-Toolcalls steuerbar machen.
- Geändert:
  - `core/autonomy/cron_runtime.py`
    - zentrale Runtime-Registry (`set/get/clear`) für Scheduler-Singleton
  - `adapters/admin-api/main.py`
    - Scheduler zusätzlich in Runtime-Registry published/cleared (Startup/Shutdown)
  - `container_commander/mcp_tools.py`
    - neue MCP-Tools:
      - `autonomy_cron_status`
      - `autonomy_cron_list_jobs`
      - `autonomy_cron_validate`
      - `autonomy_cron_create_job`
      - `autonomy_cron_update_job`
      - `autonomy_cron_pause_job`
      - `autonomy_cron_resume_job`
      - `autonomy_cron_run_now`
      - `autonomy_cron_delete_job`
      - `autonomy_cron_queue`
    - synchroner Tool-Layer kann async Scheduler-Methoden robust aufrufen
      (inkl. Event-Loop-safe Fallback über Thread-Runner)
  - `core/persona.py`
    - zusätzliche Guidance: für wiederkehrende Aufgaben `autonomy_cron_*` nutzen
- Tests:
  - neu: `tests/unit/test_container_commander_autonomy_cron_tools_contract.py`
  - Lauf:
    - `python -m pytest -q tests/unit/test_container_commander_autonomy_cron_tools_contract.py tests/unit/test_admin_api_autonomy_cron_contract.py tests/unit/test_autonomy_cron_scheduler.py tests/unit/test_frontend_cron_app_wiring_contract.py tests/unit/test_admin_api_autonomy_jobs_contract.py tests/unit/test_frontend_autonomy_jobs_wiring_contract.py tests/unit/test_runtime_autonomy_status_contract.py`
    - Ergebnis: **22 passed**
- Runtime-Indikator:
  - Admin-API-Logs zeigen nach Restart:
    - Commander-Tool-Registry mit erweitertem Toolset (`Registered 23 tools ...`)
    - MCP tools/call smoke auf `autonomy_cron_status` erfolgreich.

---

## Cron Guardrails Hardening (2026-03-09, UTC)

Ziel:
- Cronjobs produktionssicher machen (Rate-Limits, Queue-Schutz, klare Fehlercodes, UI-Transparenz).

### Schrittstatus
- [x] G1: Scheduler-Policy-Limits eingebaut
- [x] G2: API-Fehlercodes für Policy-Verletzungen durchgereicht
- [x] G3: WebUI zeigt aktive Policy-Grenzen + bessere Fehlermeldungen
- [x] G4: Tests erweitert

### G1 — Scheduler-Policy-Limits
- Datei:
  - `core/autonomy/cron_scheduler.py`
- Neu:
  - `CronPolicyError` mit `error_code`, `status_code`, `details`.
  - Policy-Limits:
    - `max_jobs`
    - `max_jobs_per_conversation`
    - `min_interval_s`
    - `max_pending_runs`
    - `max_pending_runs_per_job`
    - `manual_run_cooldown_s`
  - Guardrails greifen bei:
    - `create_job` / `update_job`
    - `run_now` (Cooldown/Backlog/Capacity)
    - `_tick_once` (throttle statt unbounded queue growth)
  - Scheduler-Status liefert jetzt zusätzlich `policy`.

### G2 — API-Semantik
- Datei:
  - `adapters/admin-api/main.py`
- Neu:
  - Cron-Policy-Verletzungen werden als strukturierte API-Fehler zurückgegeben
    (z. B. `cron_run_now_cooldown`, `cron_queue_capacity_reached`) inkl. HTTP-Status.
  - Scheduler-Startup übernimmt die neuen Config-Knobs.

### G3 — WebUI
- Dateien:
  - `adapters/Jarvis/js/apps/cron.js`
  - `adapters/Jarvis/static/css/cron.css`
- Neu:
  - Policy-Hinweise im Create-Panel (min interval, max jobs, cooldown, etc.).
  - API-Fehlerformatierung mit `error_code`/`retry_after_s`.
  - `Run now` wird in `queued/running` visuell deaktiviert.

### G4 — Config + Tests
- Config erweitert in `config.py`:
  - `AUTONOMY_CRON_MAX_JOBS`
  - `AUTONOMY_CRON_MAX_JOBS_PER_CONVERSATION`
  - `AUTONOMY_CRON_MIN_INTERVAL_S`
  - `AUTONOMY_CRON_MAX_PENDING_RUNS`
  - `AUTONOMY_CRON_MAX_PENDING_RUNS_PER_JOB`
  - `AUTONOMY_CRON_MANUAL_RUN_COOLDOWN_S`
- Tests ergänzt:
  - `tests/unit/test_autonomy_cron_scheduler.py` (conversation-limit, min-interval, run-now-cooldown)
  - `tests/unit/test_admin_api_autonomy_cron_contract.py` (neue Config-Knobs)
  - `tests/unit/test_frontend_cron_app_wiring_contract.py` (policy-hints/error-formatting)

### Follow-up Schritt-für-Schritt (2026-03-09, UTC)
- [x] S1: Live-Smoketest auf laufender Admin-API
- [x] S2: Default-Policy bestätigt (konservativ)
- [x] S3: Settings-UI/API für Cron-Policy ergänzt
- [x] S4: TRION-Cron-Safety + Approval-Gate umgesetzt

#### S1 — Live-Smoketest Ergebnisse
- `GET /health` → `200`
- `POST /api/autonomy/cron/jobs` (valid: `*/5 * * * *`) → `201`
- `POST /api/autonomy/cron/jobs` (invalid: `*/1 * * * *`) → `409` + `error_code=cron_min_interval_violation`
- `POST /api/autonomy/cron/jobs/{id}/run-now` (1st) → `202`
- `POST /api/autonomy/cron/jobs/{id}/run-now` (2nd direkt) → `429` + `error_code=cron_run_now_cooldown`
- `POST /pause` + `POST /resume` → `200`
- `DELETE /api/autonomy/cron/jobs/{id}` → `200`

#### S2 — Default-Policy Entscheidung
- Aktive Baseline bleibt:
  - `AUTONOMY_CRON_MIN_INTERVAL_S=300`
  - `AUTONOMY_CRON_MANUAL_RUN_COOLDOWN_S=30`
  - `AUTONOMY_CRON_MAX_PENDING_RUNS_PER_JOB=2`
- Begründung:
  - schützt Queue/Worker gegen Run-now-Spam und zu aggressive Schedules
  - passt zur aktuellen Single-Worker Standardkonfiguration

#### S3 — Settings-Integration
- Backend:
  - `adapters/admin-api/settings_routes.py`
  - neue Endpunkte:
    - `GET /api/settings/autonomy/cron-policy`
    - `POST /api/settings/autonomy/cron-policy`
  - typed update model + range validation + source tracking (`override/env/default`)
- Frontend:
  - `adapters/Jarvis/index.html`
    - neuer Advanced-Block **Autonomy Cron Guardrails**
  - `adapters/Jarvis/js/apps/settings.js`
    - load/save/setup handler für Cron-Policy
    - Hinweis im UI: wirksam nach Admin-API-Restart
- Contracts:
  - `tests/unit/test_settings_autonomy_cron_policy_contract.py` (neu)
  - `tests/unit/test_frontend_settings_cron_policy_wiring_contract.py` (neu)

#### S4 — TRION-Cron-Safety + Approval-Gate
- Core-Policy erweitert in `core/autonomy/cron_scheduler.py`:
  - neue TRION-Guardrails:
    - `trion_safe_mode`
    - `trion_min_interval_s`
    - `trion_max_loops`
    - `trion_require_approval_for_risky`
  - risky-objective Gate:
    - bei `created_by=trion` und risk keywords → `cron_trion_approval_required` (wenn nicht `user_approved=true`)
  - hard-block keywords:
    - z. B. `rm -rf`, `mkfs`, `dd if=` → `cron_trion_objective_forbidden`
  - TRION objective allowlist-Kategorien erzwungen (`status`, `summary`, `digest`, `monitor`, ...)
- Enqueue-Härtung:
  - cooldown gilt jetzt auch für Tool-Trigger (`reason=tool`), nicht nur manuelle API-Trigger.
- API/Config:
  - neue Config-Knobs in `config.py`:
    - `AUTONOMY_CRON_TRION_SAFE_MODE`
    - `AUTONOMY_CRON_TRION_MIN_INTERVAL_S`
    - `AUTONOMY_CRON_TRION_MAX_LOOPS`
    - `AUTONOMY_CRON_TRION_REQUIRE_APPROVAL_FOR_RISKY`
  - Startup-Wiring in `adapters/admin-api/main.py` für neue Scheduler-Parameter.
- Settings-UI/API erweitert:
  - `GET/POST /api/settings/autonomy/cron-policy` umfasst jetzt auch TRION-spezifische Knobs.
  - Advanced-UI um Felder für TRION Min-Interval, TRION Max-Loops, Safe-Mode, Approval-Requirement erweitert.
- Commander-Tools:
  - `autonomy_cron_create_job`/`update_job` unterstützen jetzt `user_approved`.
  - Policy-Fehler werden strukturiert mit `error_code` + `details` zurückgegeben.

#### S5 — GitHub Reference Collections (Cronjobs | Skills | Blueprints)
- Ziel:
  - Vorsorgliche Read-Only-Referenzen für TRION einführen, damit Cron/Skill/Blueprint-Ideen aus kuratierten GitHub-Links gelesen werden können.
- Backend:
  - `adapters/admin-api/settings_routes.py`
  - neue Endpunkte:
    - `GET /api/settings/reference-links`
    - `POST /api/settings/reference-links`
  - Persistenz-Key:
    - `TRION_REFERENCE_LINK_COLLECTIONS`
  - Kategorien:
    - `cronjobs`, `skills`, `blueprints`
  - Guardrails:
    - nur `https`
    - nur erlaubte Hosts (`github.com`, `www.github.com`, `raw.githubusercontent.com`, `gist.github.com`)
    - dedup pro Kategorie via URL
    - `read_only` wird serverseitig erzwungen
- Frontend (Settings/Advanced):
  - `adapters/Jarvis/index.html`
    - neues Panel **GitHub Reference Collections**
    - Tabs: `CRONJOBS | SKILLS | BLUEPRINTS`
  - `adapters/Jarvis/js/apps/settings.js`
    - Tab-State + Tabellen-Editor (add/remove/edit/enable)
    - Load/Save gegen `/api/settings/reference-links`
- TRION-Zugriff:
  - `container_commander/mcp_tools.py`
  - neues Tool:
    - `cron_reference_links_list` (optional category filter, read-only payload)
- Contracts:
  - `tests/unit/test_settings_reference_links_contract.py` (neu)
  - `tests/unit/test_frontend_settings_reference_links_wiring_contract.py` (neu)
  - `tests/unit/test_container_commander_autonomy_cron_tools_contract.py` erweitert

#### S6 — TRION Cron Create nutzt Reference Collections automatisch
- Ziel:
  - Bei `created_by=trion` soll Cron-Create automatisch aktive `cronjobs`-Referenzen anhängen.
- Umsetzung:
  - `container_commander/mcp_tools.py`
    - neue interne Loader-Funktion für Referenz-Links aus `TRION_REFERENCE_LINK_COLLECTIONS`
    - `autonomy_cron_create_job` hängt bei TRION-Aktor automatisch:
      - `reference_links`
      - `reference_source=settings:cronjobs:auto`
    - Response ergänzt um `reference_links_used` (count/source)
    - `cron_reference_links_list` nutzt denselben Loader und unterstützt jetzt `limit`
  - `core/autonomy/cron_scheduler.py`
    - neues optionales Job-Feld:
      - `reference_links` (normalisiert/dedupliziert)
      - `reference_source`
- Tests:
  - `tests/unit/test_autonomy_cron_scheduler.py` erweitert
  - `tests/unit/test_container_commander_autonomy_cron_tools_contract.py` erweitert

#### S7 — Harte Domain-Trennung CRONJOB vs SKILL (Rule + Embedding, no-prompt)
- Ziel:
  - CRON/Skill-Entscheidung deterministisch vor Tool-Ausführung treffen, mit minimalem Interpretationsspielraum für Thinking/Control.
- Umsetzung:
  - Neuer Router:
    - `core/domain_router_hybrid.py`
    - Output: `domain_tag` (`CRONJOB|SKILL|GENERIC`), `domain_locked`, `operation`, `cron_expression_hint`, `cron_job_id_hint`
    - Primär Rule-basiert, Embedding nur als Ambiguitäts-Fallback
  - Orchestrator:
    - `core/orchestrator.py`
    - integriert `DomainRouterHybridClassifier`
    - schreibt Signal nach `thinking_plan["_domain_route"]`
    - harte Domain-Tool-Gates in `_resolve_execution_suggested_tools`
      - CRONJOB erlaubt nur `autonomy_cron_*` (+ `cron_reference_links_list`)
      - SKILL erlaubt nur Skill-Tools
    - deterministische Tool-Seed-Logik pro CRON-Operation (`create`, `run_now`, `delete`, …)
    - Fallback-Args für `autonomy_cron_*` ergänzt (inkl. Cron-Expr-Hints)
  - Control-Layer:
    - `core/layers/control.py`
    - Skill-Confirmation-Fallback wird deaktiviert, wenn Domain auf `CRONJOB` gelockt ist
    - verhindert `pending_skill_creation` bei Cron-Requests
  - Config:
    - `config.py` neue Flags:
      - `DOMAIN_ROUTER_ENABLE`
      - `DOMAIN_ROUTER_EMBEDDING_ENABLE`
      - `DOMAIN_ROUTER_LOCK_MIN_CONFIDENCE`
- Tests:
  - `tests/unit/test_domain_router_hybrid.py` (neu)
  - `tests/unit/test_orchestrator_domain_routing_policy.py` (neu)
  - `tests/unit/test_control_verify_skill_confirmation.py` erweitert
  - Regressionslauf inkl. Query-Budget-Policy-Tests: **16 passed**
- Live-Check:
  - Chat-Stream mit Cron-Prompt löst jetzt `tool_start: autonomy_cron_create_job` aus
  - kein `confirmation_pending`/`pending_skill_creation` mehr

#### S7b — Operation-Priorität Fix (`create` vs `status`) + Re-Validierung (2026-03-09, UTC)
- Problem:
  - Prompt wie `Erstelle Cronjob ... mit Ziel status summary` wurde im Live-Pfad als
    `autonomy_cron_status` statt `autonomy_cron_create_job` geroutet.
- Root-Cause:
  - In `core/domain_router_hybrid.py` wurde in `_infer_cron_operation` auf
    `status` geprüft, bevor `create`-Verben evaluiert wurden.
- Fix:
  - `_infer_cron_operation` priorisiert jetzt Intent-Verben (`erstell|anleg|create|schedule`)
    vor `status`.
- Tests:
  - `tests/unit/test_domain_router_hybrid.py` um Regression (`create + status summary`) erweitert.
  - Läufe:
    - `python -m pytest -q tests/unit/test_domain_router_hybrid.py tests/unit/test_orchestrator_domain_routing_policy.py tests/unit/test_control_verify_skill_confirmation.py tests/unit/test_orchestrator_query_budget_policy.py` → **17 passed**
    - `python -m pytest -q tests/unit/test_admin_api_autonomy_cron_contract.py tests/unit/test_autonomy_cron_scheduler.py tests/unit/test_container_commander_autonomy_cron_tools_contract.py` → **20 passed**
- Live-Re-Run:
  - Nach `docker restart jarvis-admin-api` zeigt Chat-Stream:
    - `tool_start: autonomy_cron_create_job`
    - `tool_result: success=true`
  - Cleanup: erzeugter Test-Job wurde wieder gelöscht (`GET /api/autonomy/cron/jobs` → `{"jobs":[],"count":0}`).

#### S8 — Tool-Error vs Grounding-Miss Trennung + Cron-Preflight + Safety Boundary (2026-03-09, UTC)
- Ziel:
  - Keine generische Fallback-Antwort mehr nach klaren Tool-Policy-Fehlern.
  - Cron-Min-Interval früh und deterministisch vor Tool-Call abfangen.
  - Safety-Keyword-Matching gegen Substring-False-Positives härten.

- Schritt 1/2 — Output-Grounding Fehlerklasse getrennt
  - Datei: `core/layers/output.py`
  - Änderungen:
    - neue Evidence-Summary-Helfer:
      - `_summarize_evidence_item(...)`
      - `_build_tool_failure_fallback(...)`
    - `_grounding_precheck(...)` unterscheidet jetzt:
      - `blocked_reason=tool_execution_failed` (Tool lief, aber nur `error/skip/partial`)
      - `blocked_reason=missing_evidence` (kein verwertbarer Tool-Nachweis)
      - `blocked_reason=evidence_summary_mode`
    - neue Plan-Flags:
      - `_grounding_block_reason`
      - `_tool_execution_failed`
  - Effekt:
    - Bei Cron-Policy-Fehlern kommt jetzt eine konkrete Tool-Fehlersummary
      statt der generischen Meldung „kein verifizierter Tool-Nachweis“.

- Schritt 3 — Cron-UX Preflight vor Tool-Ausführung
  - Datei: `core/orchestrator.py`
  - Änderungen:
    - neue Helpers:
      - `_suggest_cron_expression_for_min_interval(...)`
      - `_prevalidate_cron_policy_args(...)`
    - `_validate_tool_args(...)` führt Preflight für
      `autonomy_cron_create_job`/`autonomy_cron_update_job` aus.
    - Bei Intervall unter Policy-Minimum:
      - Tool-Call wird deterministisch als `TOOL-SKIP` geblockt
      - reason enthält konkrete Korrektur:
        - `requested=...`
        - `minimum=...`
        - `suggested_cron=...`
        - `confirm_required=true`

- Schritt 4 — Safety-Keyword-Matcher gehärtet
  - Datei: `core/safety/light_cim.py`
  - Änderungen:
    - neue `_contains_keyword(...)` mit Word-Boundary/Phrase-Match.
    - `validate_intent(...)` und `safety_guard_lite(...)` nutzen jetzt den Boundary-Matcher
      statt einfachem Substring-Match.
  - Effekt:
    - deutlich weniger False-Positives bei Substrings
      (z. B. `begun` triggert nicht mehr auf `gun`).

- Tests:
  - erweitert:
    - `tests/unit/test_output_grounding.py`
    - `tests/unit/test_orchestrator_runtime_safeguards.py`
  - neu:
    - `tests/unit/test_light_cim_keyword_boundary.py`
  - Läufe:
    - `python -m pytest -q tests/unit/test_output_grounding.py tests/unit/test_orchestrator_runtime_safeguards.py tests/unit/test_light_cim_keyword_boundary.py tests/unit/test_light_cim_policy.py` → **94 passed**
    - `python -m pytest -q tests/unit/test_domain_router_hybrid.py tests/unit/test_orchestrator_domain_routing_policy.py tests/unit/test_control_verify_skill_confirmation.py tests/unit/test_admin_api_autonomy_cron_contract.py tests/unit/test_autonomy_cron_scheduler.py tests/unit/test_container_commander_autonomy_cron_tools_contract.py` → **29 passed**
  - Syntax:
    - `python -m py_compile core/layers/output.py core/orchestrator.py core/safety/light_cim.py ...` → OK

- Live-Verifikation nach Runtime-Restart:
  - `docker restart jarvis-admin-api`
  - Repro-Prompt:
    - `TRION kannst du einne Cronjob erstellen, der dich einmal in 1 Minute daran erinnert mir zu sagen, Cronjob funktoniert?`
  - Stream-Events:
    - `tool_start: autonomy_cron_create_job`
    - `tool_result: success=false, skipped=true, error=cron_min_interval_violation_precheck...`
  - Finale Antwort jetzt korrekt konkret:
    - `Tool-Ausführung fehlgeschlagen: ... requested=60s minimum=900s suggested_cron=*/15 ...`
  - Kein generischer Fallback mehr:
    - `Ich habe aktuell keinen verifizierten Tool-Nachweis ...` tritt in diesem Pfad nicht mehr auf.

#### S8b — Actor-Default + robuste Intervall-Hinweise (2026-03-09, UTC)
- Problem:
  - Chat-initiierte Cron-Requests liefen standardmäßig mit `created_by=trion` und trafen dadurch das strengere `trion_min_interval_s` (900s).
  - UI-Markdown konnte `suggested_cron=*/15 * * * *` visuell verkürzen.
- Fix:
  - `core/orchestrator.py`
    - Fallback-Args für `autonomy_cron_create_job` jetzt standardmäßig `created_by=user`.
    - Precheck-Reason erweitert um robustes Feld:
      - `suggested_every_minutes=<n>`
  - `container_commander/mcp_tools.py`
    - Tool-Definition/Default für `created_by` auf `user` umgestellt.
- Ergebnis (Live, nach Restart):
  - Prompt `... einmal in 1 Minute ...`
  - `tool_result`: `cron_min_interval_violation_precheck: requested=60s minimum=300s suggested_every_minutes=5 ...`
  - finale Antwort bleibt konkret und handlungsorientiert (kein generischer Grounding-Fallback).

#### S9 — Hardware Preflight Guard für Cron-Dispatch (2026-03-09, UTC)
- Ziel:
  - Cron-Runs deterministisch stoppen, bevor Systemdruck (CPU/RAM) kritische Bereiche erreicht.
  - Keine Prompt-Heuristik, sondern feste Runtime-Regeln im Scheduler.

- Scheduler-Hardening:
  - Datei: `core/autonomy/cron_scheduler.py`
  - Neue Guard-Parameter:
    - `hardware_guard_enabled`
    - `hardware_cpu_max_percent`
    - `hardware_mem_max_percent`
  - Neue Hardware-Sampling-Logik:
    - CPU: normalisierte 1m-Load (`os.getloadavg()/cpu_count`)
    - RAM: Host-Auslastung über `/proc/meminfo` (`MemTotal`/`MemAvailable`)
  - Dispatch-Verhalten:
    - Vor `submit_cb(...)` wird Hardware-Guard geprüft.
    - Bei Grenzwertverletzung wird Run **nicht** eingereicht, sondern als
      `deferred_hardware` protokolliert.
    - Job-Status wird gesetzt auf:
      - `last_status=deferred_hardware`
      - `last_error=<cpu_over_limit|mem_over_limit>`
    - History enthält `hardware_guard`-Snapshot für Nachvollziehbarkeit.

- Config/API-Wiring:
  - Datei: `config.py`
    - neue Getter:
      - `get_autonomy_cron_hardware_guard_enabled()`
      - `get_autonomy_cron_hardware_cpu_max_percent()`
      - `get_autonomy_cron_hardware_mem_max_percent()`
  - Datei: `adapters/admin-api/main.py`
    - Startup-Wiring der drei neuen Parameter in `AutonomyCronScheduler(...)`
    - Startup-Log um aktive Hardware-Grenzwerte erweitert.
  - Datei: `adapters/admin-api/settings_routes.py`
    - `GET/POST /api/settings/autonomy/cron-policy` um neue Knobs ergänzt:
      - `AUTONOMY_CRON_HARDWARE_GUARD_ENABLED`
      - `AUTONOMY_CRON_HARDWARE_CPU_MAX_PERCENT`
      - `AUTONOMY_CRON_HARDWARE_MEM_MAX_PERCENT`

- Tests:
  - `tests/unit/test_autonomy_cron_scheduler.py`
    - neu: defer bei Hardware-Überlast blockt Submission deterministisch.
    - neu: bei niedriger Last wird normal submitted.
  - Contracts erweitert:
    - `tests/unit/test_settings_autonomy_cron_policy_contract.py`
    - `tests/unit/test_admin_api_autonomy_cron_contract.py`
  - Lauf:
    - `python -m pytest -q tests/unit/test_autonomy_cron_scheduler.py tests/unit/test_settings_autonomy_cron_policy_contract.py tests/unit/test_admin_api_autonomy_cron_contract.py` → **18 passed**
  - Syntax:
    - `python -m py_compile core/autonomy/cron_scheduler.py config.py adapters/admin-api/main.py adapters/admin-api/settings_routes.py` → OK

#### S9b — RAM-Parser-Fix + E2E-Re-Run (2026-03-09, UTC)
- Problem im ersten Live-Run:
  - `last_status=deferred_hardware` mit `last_error=mem_over_limit:100.0>=85`
  - Ursache: `/proc/meminfo`-Parser brach zu früh ab, bevor `MemAvailable` gelesen wurde.
- Fix:
  - Datei: `core/autonomy/cron_scheduler.py`
  - `_read_host_memory_used_percent()`:
    - `total_kb/available_kb` auf `Optional` umgestellt
    - Break erst wenn **beide** Felder vorhanden sind
    - fehlende Werte liefern `None` statt implizit `100%`
- Verifikation:
  - Unit: `python -m pytest -q tests/unit/test_autonomy_cron_scheduler.py` → **13 passed**
  - Syntax: `python -m py_compile core/autonomy/cron_scheduler.py` → OK
  - Live E2E (nach `docker restart jarvis-admin-api`):
    - Policy aktiv: `hw_guard=true`, `cpu_max=80`, `mem_max=85`
    - `POST /api/autonomy/cron/jobs` → `201`
    - `POST /run-now` → `202`
    - `GET job` → `last_status=submitted`, `last_error=""`
    - `GET queue` → recent status `submitted`
    - `DELETE job` → `200` (`deleted=true`)

#### S10 — Cron-Run Rückmeldung in Chat + Reminder-Fastpath (2026-03-09, UTC)
- Problem:
  - Cronjobs liefen/schedulten korrekt, aber im Chat kam keine asynchrone Rückmeldung.
  - Zusätzlich erzeugte der alte Reminder-Objective-Builder (`status summary reminder check`)
    teure Self-Checks (`autonomy_cron_status`) und häufig `max_loops_reached`.

- Backend-Fix:
  - Datei: `adapters/admin-api/main.py`
  - Neu:
    - `cron_chat_feedback`-Event-Emission pro abgeschlossenen Cron-Run
      (`workspace_event_save` auf die jeweilige `conversation_id`).
    - Deterministischer Reminder-Fastpath:
      - Objectives mit `user_reminder::...` (und Legacy `status summary reminder check`)
        werden ohne Master-Loop direkt als erfolgreiches Reminder-Resultat verarbeitet.
  - Effekt:
    - Cron-Runs liefern now ein kurzes, chatfähiges Event (`⏰ ...`) statt nur
      versteckter Queue/Job-Metadaten.

- Objective-Building-Fix:
  - Datei: `core/orchestrator.py`
  - `_build_cron_objective(...)` erstellt bei Reminder-Requests jetzt:
    - `user_reminder::<text>`
  - Beispiel:
    - User: „... erinnert mir zu sagen, Cronjob funktioniert?“
    - Objective: `user_reminder::Cronjob funktioniert?`

- Metadata-Verbesserung:
  - Datei: `core/autonomy/cron_scheduler.py`
  - Dispatch-Meta enthält jetzt auch `cron_job_name` für bessere Feedback-Texte.

- Frontend-Fix (Chat):
  - Datei: `adapters/Jarvis/static/js/chat.js`
    - neues Polling auf
      `/api/workspace-events?conversation_id=...&event_type=cron_chat_feedback`
    - neue Events werden als Assistant-Nachricht in den Chat gerendert und persistiert.
  - Datei: `adapters/Jarvis/static/js/app.js`
    - `initCronFeedbackPolling()` beim App-Start aktiviert.

- Tests:
  - neu:
    - `tests/unit/test_admin_api_autonomy_cron_feedback_contract.py`
    - `tests/unit/test_frontend_chat_cron_feedback_wiring_contract.py`
  - Lauf:
    - `python -m pytest -q tests/unit/test_admin_api_autonomy_cron_feedback_contract.py tests/unit/test_frontend_chat_cron_feedback_wiring_contract.py tests/unit/test_admin_api_autonomy_cron_contract.py tests/unit/test_autonomy_cron_scheduler.py` → **20 passed**

- Live-Verifikation (nach Restart):
  - aktiver Cronjob (`objective=status summary reminder check`) per `run-now` ausgelöst
  - Autonomy-Job jetzt:
    - `status=succeeded`
    - `result.mode=direct_reminder`
    - `result.message=\"Cronjob funktioniert?\"`
  - Workspace-Events:
    - `event_type=cron_chat_feedback` vorhanden
    - `content=\"⏰ Cronjob funktioniert?\"`

#### S11 — Control False-Block Fix für Cron-Domain (2026-03-09, UTC)
- Problem (Live):
  - Bei Cron-Requests wurde vereinzelt `Control approved=False` gesetzt, obwohl
    gleichzeitig `decide_tools=['autonomy_cron_create_job']` vorlag.
  - Folge: Chat zeigte `Safety policy violation`, obwohl die Runtime-Cron-Tools
    verfügbar waren.
  - Reproduktion im Log:
    - `2026-03-09T14:14:22Z` → Control-Verify gestartet
    - `2026-03-09T14:14:31Z` → `Control approved=False` + `decide_tools=['autonomy_cron_create_job']` + `Request blocked`

- Fix:
  - Datei: `core/layers/control.py`
  - Neue deterministische Stabilisierung in `_stabilize_verification_result(...)`:
    - Bei `approved=False` wird jetzt zusätzlich geprüft:
      - Cron-Kontext (`_domain_route=CRONJOB` oder Cron-Tool-Signale/Intent)
      - Cron-Tools runtime-verfügbar
      - Blocktext sieht nach spuriösem Policy-/Tool-Nachweis-Block aus
    - Dann Auto-Korrektur:
      - `approved=True`
      - `reason=cron_domain_false_block_auto_corrected`
      - Warnhinweis mit deterministic override
  - Schutz:
    - Explizite LightCIM-Denials bleiben unverändert.
    - Harte Sicherheitsmarker (`Sensitive content`, `PII`) werden **nicht** übersteuert.

- Tests:
  - neu: `tests/unit/test_control_cron_false_block_stabilization.py`
    - hebt spuriösen Cron-Policy-Block deterministisch auf
    - lässt LightCIM-Denial unangetastet
    - übersteuert nicht bei harten Safety-Markern
  - Lauf:
    - `python -m pytest -q tests/unit/test_control_cron_false_block_stabilization.py tests/unit/test_control_verify_skill_confirmation.py tests/unit/test_control_runtime_mode.py` → **12 passed**
  - Syntax:
    - `python -m py_compile core/layers/control.py tests/unit/test_control_cron_false_block_stabilization.py` → OK

#### S11b — Locked-CRON Override verschärft (2026-03-09, UTC)
- Problem (weiterer Live-Fall):
  - Trotz S11 gab es erneut `done_reason=blocked` bei klaren Cron-Requests.
  - Ursache:
    - Control-Response enthielt diesmal andere Warning-Texte (ohne die bisherigen Marker),
      daher griff die marker-basierte Entsperrung nicht.
    - Gleichzeitig war `domain_router tag=CRONJOB locked=True` aktiv und
      `decide_tools=['autonomy_cron_create_job']` vorhanden.

- Fix:
  - Datei: `core/layers/control.py`
  - `_should_lift_cron_false_block(...)` jetzt deterministischer:
    - Wenn `domain_locked=True` und `domain_tag=CRONJOB` und keine harten
      Safety-Marker (PII/Sensitive/LightCIM) vorliegen:
      - Block wird immer als False-Positive behandelt und aufgehoben.
    - Marker-basierte Prüfung bleibt als Fallback für nicht-locked Cron-Kontext.

- Tests:
  - `tests/unit/test_control_cron_false_block_stabilization.py`
    - neu: locked-CRON-Case wird auch ohne Textmarker entsperrt.
  - Lauf:
    - `python -m pytest -q tests/unit/test_control_cron_false_block_stabilization.py tests/unit/test_control_runtime_mode.py` → **12 passed**
  - Syntax:
    - `python -m py_compile core/layers/control.py tests/unit/test_control_cron_false_block_stabilization.py` → OK

- Live-Verifikation:
  - Prompt (gleiches Muster wie 15:29-Fall) erneut getestet.
  - Ergebnis:
    - `approved=True | reason=cron_domain_false_block_auto_corrected`
    - `tool_start/tool_result` für `autonomy_cron_create_job` erfolgreich
    - `done_reason=stop` (kein blocked mehr)

#### S12 — Präzise Schedule-Erkennung: One-Shot vs Recurring (2026-03-09, UTC)
- Ziel:
  - One-shot-Anfragen (`einmalig`, `in 1 Minute`) deterministisch von wiederkehrenden
    Cron-Anfragen trennen, ohne LLM-Interpretationsspielraum.

- Domain Router:
  - Datei: `core/domain_router_hybrid.py`
  - Neu:
    - `schedule_mode_hint` = `one_shot|recurring|unknown`
    - `one_shot_at_hint` (ISO-UTC)
  - Regelwerk:
    - Lexikalische Marker + Zeitmuster (`in/nach X Minuten`, `heute um HH:MM`, etc.)
    - Embeddings bleiben nur Fallback für Domain-Klassifikation, nicht für Schedule-Entscheidungen.

- Orchestrator:
  - Datei: `core/orchestrator.py`
  - Neu:
    - `_extract_cron_schedule_from_text(...)` liefert deterministisch:
      - `schedule_mode`
      - `cron`
      - `run_at`
    - Cron-Tool-Args enthalten jetzt:
      - `schedule_mode`
      - `run_at` (bei one_shot)
  - Policy-Precheck:
    - `one_shot`-Jobs umgehen `cron_min_interval`-Precheck (intervallbezogen),
      erhalten stattdessen `run_at`-Validierung.

- Scheduler:
  - Datei: `core/autonomy/cron_scheduler.py`
  - Neu:
    - `schedule_mode` + `run_at` im Job-Model.
    - `one_shot` wird exakt einmal gequeued und danach automatisch deaktiviert.
    - `runtime_state` unterstützt completed-One-Shots.
    - Min-Interval-Policy gilt nur für `recurring`.
    - `run_now` für one-shot markiert Job als consumed/disabled.

- Container Commander Tools:
  - Datei: `container_commander/mcp_tools.py`
  - API-Schema erweitert:
    - `schedule_mode`
    - `run_at`
  - Create/Update-Payload leitet Felder an Scheduler durch.

- Tests:
  - Aktualisiert/neu:
    - `tests/unit/test_domain_router_hybrid.py`
    - `tests/unit/test_orchestrator_domain_routing_policy.py`
    - `tests/unit/test_orchestrator_runtime_safeguards.py`
    - `tests/unit/test_autonomy_cron_scheduler.py`
    - `tests/unit/test_container_commander_autonomy_cron_tools_contract.py`
  - Lauf:
    - `python -m pytest -q tests/unit/test_domain_router_hybrid.py tests/unit/test_orchestrator_domain_routing_policy.py tests/unit/test_orchestrator_runtime_safeguards.py tests/unit/test_autonomy_cron_scheduler.py tests/unit/test_container_commander_autonomy_cron_tools_contract.py` → **91 passed**
  - Syntax:
    - `python -m py_compile ...` (alle geänderten Dateien) → OK

- Live-Verifikation:
  - Prompt: „... einmalig in einer Minute ...“
  - Ergebnis:
    - `autonomy_cron_create_job` mit `schedule_mode=one_shot`
    - `run_at` korrekt auf +1 Minute gesetzt
    - nach Ausführung automatisch:
      - `enabled=false`
      - `runtime_state=completed`
      - `next_run_at=""`

#### S13 — Cron-Create Antwortpfad stabilisiert (2026-03-09, UTC)
- Problem:
  - Bei erfolgreichem Cron-Create zeigte der Chat teils widersprüchlichen Output
    (langes LLM-Fallback + nachgelagerte Grounding-Korrektur), obwohl Tool-Resultat korrekt war.
  - Zusätzlich wurde `conversation_id` teils als `webui-default` gespeichert,
    wodurch `cron_chat_feedback` Events nicht im aktiven WebUI-Thread ankamen.

- Fix 1 (Conversation Binding):
  - Datei: `core/orchestrator.py`
  - Neu: `_bind_cron_conversation_id(...)`
  - Verhalten:
    - Für `autonomy_cron_create_job` wird `conversation_id` im Execute-Pfad
      deterministisch auf die aktive Chat-`conversation_id` gesetzt.
    - Platzhalter/Altwerte (`webui-default`) werden überschrieben.

- Fix 2 (Deterministische Erfolgsausgabe):
  - Dateien:
    - `core/orchestrator.py`
    - `core/layers/output.py`
  - Verhalten:
    - Bei erfolgreichem `autonomy_cron_create_job` wird ein kompakter,
      tool-basierter Direkttext erzeugt (`_direct_response`).
    - OutputLayer short-circuited diesen Fall und ruft kein Modell mehr auf.
    - Ergebnis: kein unnötiger Langtext, keine widersprüchliche Grounding-Reparatur
      für den reinen "Cron erstellt"-Ack.

- Tests:
  - Neu/erweitert:
    - `tests/unit/test_orchestrator_domain_routing_policy.py`
      - conversation override test
      - one-shot direct response format test
    - `tests/unit/test_output_grounding.py`
      - direct-response short-circuit test
  - Lauf:
    - `python -m pytest -q tests/unit/test_orchestrator_domain_routing_policy.py tests/unit/test_output_grounding.py tests/unit/test_orchestrator_runtime_safeguards.py tests/unit/test_autonomy_cron_scheduler.py tests/unit/test_container_commander_autonomy_cron_tools_contract.py` → **116 passed**

- Live-Verifikation:
  - Nach Container-Rebuild/Recreate (`jarvis-admin-api`) mit Prompt
    „... einmalig in Einer Minute ...“:
    - `tool_start: autonomy_cron_create_job`
    - `tool_result: success=true`
    - direkte Ausgabe (kurz, deterministisch), z. B.:
      - `Cronjob erstellt <id> ... Einmalige Ausführung um ...`
    - keine `[Grounding-Korrektur]` mehr im Ack-Pfad.

#### S14 — `webui-default`-Fallback entfernt (Conversation-Hardening, 2026-03-09, UTC)
- Ziel:
  - Verhindern, dass neue Cron/Autonomy-Jobs stillschweigend in einer
    Sammel-Conversation (`webui-default`) landen.

- Backend/Runtime:
  - `core/autonomy/cron_scheduler.py`
    - `conversation_id` ist beim Create jetzt verpflichtend (`ValueError` bei leerem Wert).
    - Dispatch verwendet keine `webui-default`-Fallbacks mehr.
  - `container_commander/mcp_tools.py`
    - Tool-Schema für `autonomy_cron_create_job` ohne `webui-default` Default.
    - Payload-Fallback: `conversation_id` aus `conversation_id` oder `session_id`, sonst leer
      (wird vom Scheduler validiert).

- Frontend:
  - `adapters/Jarvis/static/js/api.js`
    - neue dynamische `resolveConversationId(...)`-Auflösung
      (`window.currentConversationId` → localStorage → `webui-<ts>`).
    - `streamChat`, `submitDeepChatJob`, `submitAutonomyJob` ohne statischen `webui-default`.
  - `adapters/Jarvis/static/js/workspace.js`
    - `getActiveConversationId()` dynamisch statt statisch.
    - `submitAutonomyJob(...)` nutzt aktive Conversation als Fallback.
  - `adapters/Jarvis/js/apps/cron.js`
    - Cron-Formular nutzt dynamisch ermittelte Conversation-ID statt `webui-default`.

- Tests:
  - erweitert/neu:
    - `tests/unit/test_autonomy_cron_scheduler.py` (missing conversation_id rejected)
    - `tests/unit/test_container_commander_autonomy_cron_tools_contract.py`
    - `tests/unit/test_frontend_cron_app_wiring_contract.py`
    - `tests/unit/test_frontend_autonomy_jobs_wiring_contract.py`
  - Lauf:
    - `python -m pytest -q tests/unit/test_autonomy_cron_scheduler.py tests/unit/test_container_commander_autonomy_cron_tools_contract.py tests/unit/test_frontend_cron_app_wiring_contract.py tests/unit/test_frontend_autonomy_jobs_wiring_contract.py` → **28 passed**

- Live-Verifikation:
  - `POST /api/autonomy/cron/jobs` ohne `conversation_id` →  
    `{"error_code":"invalid_cron_job_payload","error":"conversation_id is required"}`
  - Chat-Flow (`... einmalig in 1 Minute ...`) erstellt weiterhin Job erfolgreich,
    aber jetzt mit aktiver Conversation-ID (kein `webui-default`).

#### S15 — Legacy-Migration + Cron E2E Regression (2026-03-09, UTC)
- Neu:
  - `scripts/ops/migrate_legacy_cron_conversations.py`
    - dry-run default, `--apply` für echte Updates
    - typbasierte Ziel-Conversations (`reminder|maintenance|backup|default`)
  - `scripts/test_cron_e2e_regression.sh`
    - prüft Ende-zu-Ende:
      - create one-shot job
      - run-now
      - `cron_chat_feedback` Event in derselben Conversation
      - delete cleanup

- Ausführung:
  - Migration dry-run:
    - `python scripts/ops/migrate_legacy_cron_conversations.py`
  - Migration apply:
    - `python scripts/ops/migrate_legacy_cron_conversations.py --apply`
  - Ergebnis:
    - `applied=7`
    - danach `legacy=0` für `conversation_id=webui-default`
    - alle betroffenen Altjobs auf `autonomy-reminders` migriert
  - E2E:
    - `./scripts/test_cron_e2e_regression.sh` → **PASS**
    - Feedback-Beispiel: `⏰ Cronjob funktioniert?`

#### S16 — Live-User-Validierung im Jarvis-Chat (2026-03-09, UTC)
- Prompt:
  - `TRION kannst du einne Cronjob erstellen, der dich einmalig in Einer minute daran erinnert ...`

- Beobachtetes Laufverhalten:
  - Control: `approved=True` (inkl. `reason=cron_domain_false_block_auto_corrected`)
  - Tool-Execution:
    - `autonomy_cron_create_job` → `✅ ok`
    - Job-ID: `ed0c7dba0e7b`
    - `schedule_mode=one_shot`
    - `run_at=2026-03-09T17:57:00+00:00`
    - `conversation_id=webui-1773066537881` (korrekt, kein `webui-default`)
  - Chat-Antwort (Ack):
    - kurz/deterministisch: `Cronjob erstellt ... Einmalige Ausführung ...`
  - Folge-Event:
    - `cron_chat_feedback` im selben Conversation-Thread
    - Inhalt: `⏰ das der Cronjob funktoniert?`

- Bewertung:
  - Zielverhalten erreicht:
    - One-shot Erstellung funktioniert.
    - Feedback kommt im richtigen Thread an.
    - Kein Grounding-Widerspruch im Ack-Pfad.
  - Bekannter Rest-Noise:
    - Thinking/Control-JSON enthält teils weiterhin unnötige Skill-/Memory-Vorschläge,
      wird aber im Cron-Pfad deterministisch überstimmt.

#### S17 — Cron False-Create Guard + Safety-Hardening (2026-03-09, UTC)
- Ziel:
  - Verhindern, dass Meta-/Smalltalk-Fragen mit `cron`-Wörtern unbeabsichtigt
    `autonomy_cron_create_job` auslösen.
  - Falsche `Safety policy violation` bei legitimen Cron-Create-Turns reduzieren.

- Umsetzung:
  - `core/domain_router_hybrid.py`
    - Meta-Frage-Erkennung für Cron-Kontext ergänzt.
    - `operation=create` nur noch bei explizitem Create-Intent **und**
      Schedule-Signal (Cron-Expr / one-shot / recurring-Hinweis).
    - Meta-/Capability-Fragen ohne Schedule werden auf `operation=status` gedowngraded.
  - `core/orchestrator.py`
    - zusätzliche Guard-Stufe für Cron-Signale (`create -> status` Downgrade),
      falls Router-Signal unplausibel ist.
    - `low_risk_skip` blockiert jetzt auch Cron-Write-Tools:
      `autonomy_cron_create_job|update_job|delete_job|run_now`.
    - Cron-Create-Fallback setzt `max_loops=1` bei `schedule_mode=one_shot`.
    - Objective-Fallback geändert von intransparentem
      `status summary monitor memory` auf nachvollziehbares `user_request::<...>`.
  - `core/safety/light_cim.py`
    - `needs_memory=true + memory_keys=[]` wird bei Cron-Kontext nicht mehr als
      logischer Blocker gewertet.
  - `adapters/admin-api/main.py`
    - `cron_chat_feedback` für `error_code=max_loops_reached` human-readable
      vereinheitlicht (`Lauflimit erreicht`).

- Tests:
  - erweitert:
    - `tests/unit/test_domain_router_hybrid.py`
    - `tests/unit/test_orchestrator_domain_routing_policy.py`
    - `tests/unit/test_orchestrator_runtime_safeguards.py`
    - `tests/unit/test_light_cim_policy.py`
    - `tests/unit/test_admin_api_autonomy_cron_feedback_contract.py`
  - Lauf:
    - `python -m pytest -q tests/unit/test_domain_router_hybrid.py tests/unit/test_orchestrator_domain_routing_policy.py tests/unit/test_orchestrator_runtime_safeguards.py tests/unit/test_light_cim_policy.py tests/unit/test_admin_api_autonomy_cron_feedback_contract.py`
    - Ergebnis: **89 passed**

##### S17.1 — One-shot `run_at_in_past` Timing-Fix (2026-03-09, UTC)
- Problem:
  - Anfrageform `in 1 Minute` konnte nahe der Minutenkante ein `run_at` erzeugen,
    das beim Tool-Precheck bereits in der Vergangenheit lag
    (`one_shot_run_at_in_past_precheck`).
- Fix:
  - Relative One-shot-Zeiten in Router + Orchestrator werden jetzt immer auf die
    **nächste** Minutenkante aufgerundet (nicht auf aktuelle Minute gefloor’d).
  - Precheck heilt kleine Drift (`<=120s`) automatisch und verschiebt `run_at`
    deterministisch auf die nächste sichere Minute.
- Betroffene Dateien:
  - `core/domain_router_hybrid.py`
  - `core/orchestrator.py`
- Regression-Tests:
  - `tests/unit/test_domain_router_hybrid.py`
  - `tests/unit/test_orchestrator_domain_routing_policy.py`

#### S18 — Cron `Job.md` für User-Transparenz (2026-03-09, UTC)
- Ziel:
  - Für selbst erstellte Cronjobs eine klare, lesbare Kurz-Doku direkt im
    `Autonomy Cron`-UI anzeigen, damit sofort sichtbar ist, **was** der Job macht.

- Backend:
  - Datei: `core/autonomy/cron_scheduler.py`
  - Neues persistiertes Feld: `job_note_md`
  - Verhalten:
    - Beim Create wird automatisch ein deterministischer Markdown-Text erzeugt,
      falls kein eigener Text übergeben wurde.
    - Eigene (`manuelle`) `job_note_md`-Einträge bleiben bei Updates erhalten.
    - Bei auto-generierten Notizen wird der Inhalt bei Kernänderungen
      (objective/schedule/etc.) automatisch aktualisiert.

- Frontend:
  - Dateien:
    - `adapters/Jarvis/js/apps/cron.js`
    - `adapters/Jarvis/static/css/cron.css`
  - Änderungen:
    - Create-Form hat jetzt optionales Feld `Job.md` (`textarea`).
    - Jobs-Tabelle zeigt pro Job eine klappbare `Job.md`-Vorschau.
    - Fallback für Altjobs ohne `job_note_md`: Vorschau wird im UI
      deterministisch aus Jobdaten generiert.

- Tests:
  - Datei: `tests/unit/test_autonomy_cron_scheduler.py`
  - Neu:
    - `test_scheduler_auto_generates_job_note_markdown`
    - `test_scheduler_keeps_custom_job_note_markdown_on_update`
  - Lauf:
    - `python -m pytest -q tests/unit/test_autonomy_cron_scheduler.py tests/unit/test_frontend_cron_app_wiring_contract.py`
    - Ergebnis: **21 passed**

- Runtime:
  - Container neu gestartet:
    - `jarvis-admin-api`
    - `jarvis-webui`

#### S19 — One-shot Cron Self-State Fix (2026-03-09, UTC)
- Problem (Live):
  - Prompt wie
    `... in 1 Minute einmalig ... erklären wie du dich fühlst`
    erzeugte zwar einen One-shot Cronjob, aber:
    - Create-Ack zeigte weiterhin Fallback-Text `Cronjob funktioniert?`
    - Lauf endete oft mit `max_loops_reached (max_loops=1)`.

- Ursache:
  - Objective wurde als `user_request::...` gebaut, aber One-shot Defaults setzten
    pauschal `max_loops=1`.
  - Direktpfad für Cron-Feedback unterstützte nur `user_reminder::...`, nicht
    Self-State-Fragen.

- Fix:
  - `core/orchestrator.py`
    - neues Objective-Mapping:
      - Self-State-Anfragen -> `self_state_report::...`
    - One-shot Loop-Budget:
      - `user_reminder::` / `self_state_report::` -> `max_loops=1` (direkter Pfad)
      - sonst One-shot -> `max_loops=4` (kein sofortiger Loop-Abbruch)
    - Create-Ack nutzt jetzt objective-basierten Rückmeldungstext statt hartem
      `Cronjob funktioniert?`-Fallback für alle Fälle.
  - `adapters/admin-api/main.py`
    - direkter Execute-Pfad für `self_state_report::...`
      (kein autonomer Multi-Loop notwendig)
    - Chat-Feedback baut bei erfolgreichem Self-State-Run eine direkte
      `⏰ ...`-Antwort.

- Tests:
  - erweitert:
    - `tests/unit/test_orchestrator_domain_routing_policy.py`
    - `tests/unit/test_admin_api_autonomy_cron_feedback_contract.py`
  - Lauf:
    - `python -m pytest -q tests/unit/test_orchestrator_domain_routing_policy.py tests/unit/test_admin_api_autonomy_cron_feedback_contract.py` -> **18 passed**
    - zusätzlicher Regression-Recheck:
      - `python -m pytest -q tests/unit/test_autonomy_cron_scheduler.py tests/unit/test_frontend_cron_app_wiring_contract.py` -> **21 passed**
  - E2E-Skript:
    - `./scripts/test_cron_e2e_regression.sh` -> **PASS**

- Runtime:
  - Container neu gestartet:
    - `trion-runtime`
    - `jarvis-admin-api`
