# TRION Session Handoff — 2026-03-09

## Was heute erledigt wurde

1. **Cron One-Shot Stabilisierung**
- Deterministische Trennung `one_shot` vs `recurring` bleibt aktiv.
- Erfolgs-Antwort für `autonomy_cron_create_job` jetzt direkt/toolbasiert (kein langer LLM-Fallback).
- `conversation_id` wird im Create-Pfad auf die aktive Chat-Conversation gebunden.

2. **`webui-default`-Fallback entfernt**
- Neue Cron-Jobs benötigen gültige `conversation_id`.
- Statische Defaults in relevanten Cron/Autonomy-Pfaden entfernt (Scheduler, MCP-Tooling, Frontend).

3. **Legacy-Cronjobs migriert**
- Script: `/home/danny/Jarvis/scripts/ops/migrate_legacy_cron_conversations.py`
- Dry-run + Apply durchgeführt.
- Ergebnis: `applied=7`, danach `legacy=0` (`webui-default` nicht mehr genutzt).

4. **E2E-Regression für Cron erstellt und ausgeführt**
- Script: `/home/danny/Jarvis/scripts/test_cron_e2e_regression.sh`
- Flow: create -> run-now -> cron_chat_feedback -> delete
- Ergebnis: **PASS**

5. **Live-User-Validierung bestätigt**
- One-shot-Job wurde erstellt (`schedule_mode=one_shot`, korrektes `run_at`).
- `cron_chat_feedback` kam im gleichen Conversation-Thread an.

6. **Container Manager Ausbau gestartet (Phasen 1+2)**
- Neues Blueprint-Runtime-Schema implementiert:
  - `ports`, `runtime`, `devices`, `environment`, `healthcheck`, `cap_add`, `shm_size`
- Persistenz/Migration in SQLite (`blueprint_store`) umgesetzt.
- Engine-Wiring ergänzt (inkl. Docker run kwargs für neue Felder).
- Port-Management integriert:
  - Precheck vor Start (`port_conflict_precheck_failed`)
  - Auto-Port-Zuweisung (`auto`/`0`, Range per `COMMANDER_AUTO_PORT_MIN/MAX`)
  - Port-Bindings als Label `trion.port_bindings` persistiert
- Neuer Port-Inspector im SysInfo-MCP:
  - `list_used_ports`, `check_port`, `find_free_port`, `list_blueprint_ports`
- Neue Tests:
  - `/home/danny/Jarvis/tests/unit/test_container_commander_blueprint_runtime_schema_contract.py`
  - `/home/danny/Jarvis/tests/unit/test_container_commander_port_management_contract.py`

7. **Container Domain Route-Lock fertiggestellt (Phase 3)**
- Domain Router erweitert: `CONTAINER` als deterministische Domain neben `CRONJOB`/`SKILL`.
- Orchestrator Domain-Gate erweitert:
  - harte Tool-Allowlist für Container-Domain
  - operation-basiertes Seed-Tool-Mapping (`deploy`, `create_blueprint`, `list`, `status`, `logs`, `stop`, `exec`)
- Dadurch werden Fehlrouten wie `create_skill` bei Container-Requests aktiv abgeschnitten.
- Neue/erweiterte Tests:
  - `/home/danny/Jarvis/tests/unit/test_domain_router_hybrid.py`
  - `/home/danny/Jarvis/tests/unit/test_orchestrator_domain_routing_policy.py`

8. **Gaming-Deploy Fundament (Phase 4 Teil A/B)**
- `request_container` liefert jetzt direkt Verbindungsinfos (`ip_address`, `ports`, `connection.endpoints`).
- Runtime-Preflight für `runtime=nvidia` hinzugefügt:
  - sauberer Fehler statt kryptischem Docker-Fail, wenn NVIDIA Runtime fehlt.
- Auto-Preset `gaming-station` integriert:
  - Steam-Headless/Sunshine Blueprint wird bei Bedarf automatisch angelegt.
  - nutzt `vault://STEAM_USERNAME` und `vault://STEAM_PASSWORD` für Credentials.
- Orchestrator-Fallbacks erweitert:
  - Gaming-Anfragen routen deterministisch auf `gaming-station`.

9. **Gaming-E2E Fixes + Live-Validierung (Phase 4 Teil C)**
- Quota-Problem behoben:
  - `request_container(gaming-station)` setzt jetzt ein quota-kompatibles Override-Profil.
  - Ergebnis im Live-Test: Deploy mit `1280m` RAM und `0.75` CPU statt starrem `8g/4.0`.
- Registry-Problem behoben:
  - Gaming-Image auf `josh5/steam-headless:latest` umgestellt (auf Host pullbar).
  - Legacy-Image-Migration in `_ensure_gaming_station_blueprint()` ergänzt.
- Trust-Liste erweitert:
  - `josh5/steam-headless` ist jetzt im Trusted-Image-Pattern.
- Live-E2E erfolgreich:
  - `request_container` -> `pending_approval` -> `approve` -> `running`
  - `container_inspect` liefert IP + Sunshine-Port-Mappings
  - `stop_container` erfolgreich, Cleanup bestätigt

10. **Readiness Hardening (Phase 4 Teil D)**
- Healthcheck-Readiness-Guard aktiv:
  - Bei Blueprints mit `healthcheck` wartet Engine auf `healthy` statt sofort `running` zu melden.
  - Timeout wird aus Healthcheck-Config abgeleitet.
- Auto-Stop/Auto-Cleanup bei Readiness-Fail:
  - `healthcheck_timeout_auto_stopped`
  - `healthcheck_unhealthy_auto_stopped`
  - `container_exited_before_ready_auto_stopped`
- Präzise API-Error-Codes statt generischem `approval_failed`:
  - `healthcheck_timeout` (504)
  - `healthcheck_unhealthy` (409)
  - `container_not_ready` (409)
- Terminal UI zeigt `deploy_failed` Events + passende Hints für diese Fälle.

## Aktueller Status
- Cron-Flow ist funktional stabil:
  - Erstellen
  - Ausführen (one-shot/run-now)
  - Feedback im Chat
  - Cleanup/Delete
- Bekannter Restpunkt:
  - Thinking/Control-Warnungen sind teils noch noisy, ohne funktionalen Impact auf den Cron-Pfad.
- Container Manager:
  - Phase 1/2/3 abgeschlossen.
  - Phase 4 abgeschlossen (Preset + Resolver + Runtime-Preflight + Live-E2E + Readiness Hardening).
  - Nächster Schritt: Cronjob-UI/Policy-Feinschliff und anschließend Skills-Stabilisierung.

## Wichtige Dateien
- `/home/danny/Jarvis/core/orchestrator.py`
- `/home/danny/Jarvis/core/layers/output.py`
- `/home/danny/Jarvis/core/autonomy/cron_scheduler.py`
- `/home/danny/Jarvis/container_commander/mcp_tools.py`
- `/home/danny/Jarvis/adapters/Jarvis/static/js/api.js`
- `/home/danny/Jarvis/adapters/Jarvis/static/js/workspace.js`
- `/home/danny/Jarvis/adapters/Jarvis/js/apps/cron.js`
- `/home/danny/Jarvis/scripts/ops/migrate_legacy_cron_conversations.py`
- `/home/danny/Jarvis/scripts/test_cron_e2e_regression.sh`
- `/home/danny/Jarvis/docs/autonomy-implementation-log-2026-03-08.md`
- `/home/danny/Jarvis/docs/container-manager-implementation-log-2026-03-09.md`

## Update 2026-03-09 23:28 UTC (Cron Self-State Regression)
- Bugklasse bestätigt: one-shot Cron mit Formulierungen wie "wie du dich ... fühlst" konnte als `user_request::...` in einen unnötigen Autonomy-Loop laufen (`max_loops_reached`).
- Fix umgesetzt:
  - `core/orchestrator.py`: `_looks_like_self_state_request(...)` eingeführt und in Objective-/Ack-Pfad verdrahtet.
  - `adapters/admin-api/main.py`: gleiche Heuristik + direkte Self-State-Erkennung auch für `user_request::...`.
- Testabdeckung erweitert:
  - `tests/unit/test_orchestrator_domain_routing_policy.py` enthält jetzt einen Regressionstest mit dem Originalsatz inkl. Tippfehlern.
  - Cron-Feedback-Contract-Test bestätigt weiterhin Self-State-Pfad.
- Verifiziert:
  - `pytest` (beide betroffenen Testdateien) grün: 21 passed.
  - `py_compile` für Orchestrator/Admin-API ohne Fehler.
  - Runtime/API Container laufen stabil.
- Morgen zuerst:
  1. Live one-shot Cron mit exakt diesem Prompt erzeugen.
  2. Nach Trigger prüfen, dass Feedback nicht mehr `max_loops` trifft und Self-State-Text kommt.
