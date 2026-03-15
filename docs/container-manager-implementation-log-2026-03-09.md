# Container Manager Implementation Log (2026-03-09)

## Ziel
Container Manager schrittweise in Richtung autonomes, deterministisches Blueprint-Deployment erweitern (Gaming/GPU/Ports/Storage-Scope vorbereitet).

## Geplante Reihenfolge
- [x] Phase 1: Blueprint-Schema-Fundament (Runtime/Ports/Hardware-Felder)
- [x] Phase 2: Port-Management (Konfliktcheck + Registry/Inspector)
- [x] Phase 3: Storage Scope Manager + Vault-Referenzen + Intent/Route-Lock
- [~] Phase 4: Steam-Headless Blueprint + Resolver/Trust + E2E

## Laufendes Protokoll
### Phase 1 abgeschlossen
- `container_commander/models.py`
  - Blueprint-Felder ergänzt:
    - `ports`, `runtime`, `devices`, `environment`, `healthcheck`, `cap_add`, `shm_size`
  - `BlueprintCreateRequest` auf dieselben Felder erweitert.
- `container_commander/blueprint_store.py`
  - SQLite-Schema + Auto-Migration für neue Felder ergänzt.
  - Persistenz (`_blueprint_to_params`, Insert/Update, `_row_to_blueprint`) erweitert.
  - Inheritance-Resolve um Runtime-Feld-Merge ergänzt.
- `container_commander/engine.py`
  - Statische Blueprint-`environment` wird vor Secret-Injektion geladen.
  - Docker-Run-Wiring für `ports`, `runtime`, `devices`, `cap_add`, `shm_size`, `healthcheck` ergänzt.
  - Neue Helper: `_build_port_bindings`, `_build_healthcheck_config`.
- `container_commander/mcp_tools.py`
  - `blueprint_create`-Schema um neue Runtime-Felder ergänzt.
  - Tool-Implementierung übernimmt neue Felder in den Blueprint.
- Tests:
  - neu: `tests/unit/test_container_commander_blueprint_runtime_schema_contract.py`

### Phase 2 abgeschlossen
- `container_commander/port_manager.py` (neu)
  - Host-Port-Utilities: `list_used_ports`, `check_port`, `find_free_port`
  - Deploy-Precheck: `validate_port_bindings`
  - Runtime-Reservierungen aus laufenden TRION-Containern: `list_blueprint_ports`
- `container_commander/engine.py`
  - Port-Conflict-Precheck vor `containers.run(...)`:
    - blockt deterministisch mit `port_conflict_precheck_failed`
  - Auto-Port-Zuweisung in `_build_port_bindings`:
    - `auto`/`0` nutzt freien Port aus `COMMANDER_AUTO_PORT_MIN/MAX` (Default `8000-9000`)
  - Range-Mappings unterstützt (z. B. `48100-48110:48100-48110/udp`)
  - Port-Bindings werden als Label persistiert (`trion.port_bindings`) für Registry/Inspect.
- `sysinfo/mcp_tools.py`
  - neuer `port_inspector` Tool-Satz:
    - `list_used_ports`
    - `check_port`
    - `find_free_port`
    - `list_blueprint_ports`
- Tests:
  - neu: `tests/unit/test_container_commander_port_management_contract.py`
  - Regressionen: bestehende Container-Manager-Contracts weiterhin grün.

### Phase 3 (Teil A/B) umgesetzt
- `container_commander/storage_scope.py` (neu)
  - Scope-Verwaltung: `list_scopes`, `get_scope`, `upsert_scope`, `delete_scope`
  - Policy-Gate: `validate_blueprint_mounts` (fail-closed)
  - Default ohne Scope: nur Projektpfad + `/tmp` für bind mounts
  - `volume`-Mounts sind davon ausgenommen
- `container_commander/models.py`
  - `MountDef.type` ergänzt (`bind|volume`)
  - `Blueprint.storage_scope` ergänzt
- `container_commander/blueprint_store.py`
  - Persistenz + Migration für `storage_scope`
- `container_commander/engine.py`
  - Scope-Validation vor Deploy (`validate_blueprint_mounts`)
  - `vault://SECRET_NAME` in `environment` wird beim Start aufgelöst (Blueprint-scope -> global fallback)
  - Secret-Audit für `vault://`-Injection (`inject_vault_ref`)
  - `volume`-Mounts werden korrekt als Volume gemountet (nicht als Host-Path normalisiert)
- `adapters/admin-api/commander_api/storage.py`
  - neue Scope-APIs:
    - `GET /storage/scopes`
    - `GET /storage/scopes/{scope_name}`
    - `POST /storage/scopes`
    - `DELETE /storage/scopes/{scope_name}`
- `container_commander/mcp_tools.py`
  - neue Tools:
    - `storage_scope_list`
    - `storage_scope_upsert`
    - `storage_scope_delete`
- Tests:
  - neu: `tests/unit/test_container_commander_storage_scope_contract.py`

### Offen in Phase 3
- keine offenen Punkte.

### Phase 3 (Teil C) abgeschlossen — Deterministischer Intent/Route-Lock
- `core/domain_router_hybrid.py`
  - neue Domain: `CONTAINER` (neben `CRONJOB`/`SKILL`)
  - neue Container-Rule-Signale + Embedding-Hybrid-Ranking
  - Container-Operation-Parsing (`deploy`, `create_blueprint`, `stop`, `status`, `logs`, `list`, `exec`)
  - `domain_locked` jetzt auch für `container`
- `core/orchestrator.py`
  - Domain-Gate erweitert um `CONTAINER`
  - feste Allowlist für Container-Domain-Tools (`request_container`, `blueprint_*`, `container_*`, `storage_scope_*`, Port-Inspector-Tools)
  - deterministisches Seed-Mapping pro Container-Operation (`deploy -> request_container`, `list -> container_list`, etc.)
- Tests:
  - erweitert: `tests/unit/test_domain_router_hybrid.py`
  - erweitert: `tests/unit/test_orchestrator_domain_routing_policy.py`

### Phase 4 (Teil A/B) umgesetzt — Gaming-Deploy Fundament
- `container_commander/engine.py`
  - Runtime-Preflight eingeführt:
    - `_validate_runtime_preflight(...)`
    - `runtime=nvidia` blockt deterministisch, wenn Docker-Runtime `nvidia` fehlt.
  - Connection-Resolver ergänzt:
    - `_extract_port_details(...)` aus Docker-Inspect
    - `_build_connection_info(...)` mit `TRION_PUBLIC_HOST`-Hint
  - `inspect_container(...)` liefert jetzt:
    - `ports`
    - `connection` (container_ip/public_host/endpoints)
- `container_commander/mcp_tools.py`
  - `request_container` liefert jetzt direkt `ip_address`, `ports`, `connection`.
  - Auto-Preset `gaming-station`:
    - `_ensure_gaming_station_blueprint()` legt bei Bedarf ein Steam-Headless/Sunshine-Blueprint an
    - inkl. `runtime=nvidia`, Sunshine-Ports, `vault://STEAM_USERNAME`/`vault://STEAM_PASSWORD`
- `core/orchestrator.py`
  - Fallback-Args für Container-Flow verbessert:
    - `request_container` erkennt Gaming-Intent und setzt `blueprint_id=gaming-station`
    - `blueprint_create` liefert deterministischen Gaming-Default bei Steam/Sunshine-Anfragen
- Tests:
  - neu: `tests/unit/test_container_commander_gaming_route_contract.py`

### Offen in Phase 4
- Optional: expliziter Readiness-Timeout/Auto-Stop für nicht gesund werdende Gaming-Container.

### Phase 4 (Teil C) abgeschlossen — Live-E2E + harte Runtime-Fixes
- `container_commander/mcp_tools.py`
  - `request_container(gaming-station)` nutzt jetzt quota-kompatibles Override-Profil:
    - neue Helper-Funktion `_compute_gaming_override_resources()`
    - verhindert Approval-Fails durch starre 8G-Anforderung bei kleinen Commander-Quotas
    - aktuelles Profil im E2E: `memory_limit=1280m`, `cpu_limit=0.75`
  - Auto-Gaming-Blueprint-Migration ergänzt:
    - Legacy-Images werden automatisch auf pullbare Quelle umgestellt
    - aktuell: `josh5/steam-headless:latest`
- `container_commander/trust.py`
  - Trusted-Image-Pattern erweitert um:
    - `josh5/steam-headless`
- `core/orchestrator.py`
  - deterministischer Gaming-Fallback für `blueprint_create` auf neues Image umgestellt:
    - `josh5/steam-headless:latest`
- Tests:
  - aktualisiert: `tests/unit/test_container_commander_gaming_route_contract.py`
  - Regression (gezielt) grün:
    - `test_container_commander_gaming_route_contract.py`
    - `test_container_commander_port_management_contract.py`
    - `test_container_commander_storage_scope_contract.py`
    - Ergebnis: `13 passed`

### Live-E2E Ergebnis (internes Docker-Netz)
- E2E erfolgreich über internen Pfad `trion-runtime -> jarvis-admin-api`:
  1. `request_container(gaming-station)` → `pending_approval`
  2. `POST /api/commander/approvals/{id}/approve` → `approved: true`
  3. `container_inspect` liefert Verbindung/Ports:
     - `container_ip: 172.17.0.5`
     - `127.0.0.1:47984/tcp`
     - `127.0.0.1:47989/tcp`
     - `127.0.0.1:48010/tcp`
     - `127.0.0.1:48100-48110/udp`
  4. `stop_container` → `stopped: true`
  5. Cleanup verifiziert: nur `trion-home` läuft

### Hinweis zur Testumgebung
- Host-Port-Zugriff auf `127.0.0.1:8200` war in der aktuellen Sandbox-Session inkonsistent.
- Verifikation deshalb über internes Docker-Service-Routing durchgeführt (funktional äquivalent für Backend-E2E).

### Phase 4 (Teil D) abgeschlossen — Readiness-Guard + Auto-Stop Hardening
- `container_commander/engine.py`
  - Readiness-Gate implementiert, wenn `healthcheck` gesetzt ist:
    - wartet deterministisch auf Docker-Health `healthy`
    - Timeout wird aus Healthcheck-Parametern abgeleitet (`_derive_readiness_timeout_seconds`)
  - Harte Failure-Pfade mit Auto-Cleanup:
    - `healthcheck_timeout_auto_stopped`
    - `healthcheck_unhealthy_auto_stopped`
    - `container_exited_before_ready_auto_stopped`
  - Bei Readiness-Fail:
    - Container wird entfernt
    - neu erzeugtes Workspace-Volume wird entfernt
    - WS-Event `deploy_failed` wird emittiert
  - API-Fehler im Start-Pfad gefixt:
    - Volume-Cleanup nach `APIError` nur noch bei neu erzeugtem Volume (kein Löschen von `resume_volume`).
- `adapters/admin-api/commander_routes.py`
  - Deploy-Route mappt Runtime-Readiness-Fails auf präzise Codes:
    - `healthcheck_timeout` (HTTP 504)
    - `healthcheck_unhealthy` (HTTP 409)
    - `container_not_ready` (HTTP 409)
- `adapters/admin-api/commander_api/operations.py`
  - Approval-Route (`/approvals/{id}/approve`) mappt dieselben Readiness-Codes (statt generischem `approval_failed`).
- `container_commander/mcp_tools.py`
  - `request_container` liefert bei Runtime-Fehlern zusätzlich `error_code` mit derselben Klassifikation.
- `adapters/Jarvis/js/apps/terminal.js`
  - WS-Event `deploy_failed` wird sichtbar geloggt + Toast.
  - `suggestFix(...)` und API-Hints um Readiness-Fälle erweitert.

### Live-Check Teil D
- Neuer Guard live verifiziert (internes Docker-Netz):
  1. `request_container(gaming-station)` -> `pending_approval`
  2. Approval ausgeführt
  3. Response: `error_code=container_not_ready` + `container_exited_before_ready_auto_stopped`
  4. Cleanup verifiziert: kein hängender Gaming-Container (nur `trion-home` läuft)
