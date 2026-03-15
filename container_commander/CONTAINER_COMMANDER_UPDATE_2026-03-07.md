# Container Commander Update - 2026-03-07

## Scope
Diese Datei dokumentiert alle heute umgesetzten Fixes und Neuerungen am Container Commander (Backend, Admin-API, WebUI, Contracts, Tests, Runtime).

## 1) WebSocket + Runtime Hardening

### `container_commander/ws_stream.py`
- Log- und Shell-Stream sauber getrennt (`stream: logs | shell`).
- PTY-Session-Handling auf `pro websocket + container` umgestellt.
- Resize auf Exec-PTY (`exec_resize`) statt Container-Resize.
- Robustere Cleanup-Logik bei Detach/Disconnect (Log-Tasks + PTY-Sockets + Indexe).
- Einheitlicher Activity-Emitter hinzugefuegt: `emit_activity(...)`.

### `container_commander/engine.py`
- WS-Aktivitaets-Events in den Lifecycle integriert:
  - `deploy_start`
  - `container_started`
  - `container_stopped`
  - `trust_block`
  - `container_ttl_expired`
- Event-Emission als best-effort helper (`_emit_ws_activity`).

### `container_commander/approval.py`
- Approval-History hinzugefuegt (`_history`) statt nur Pending-In-Memory.
- Pending-Approvals werden bei Resolve/Expiry aus Pending entfernt und in History uebernommen.
- Live-Events integriert:
  - `approval_requested`
  - `approval_resolved` (approved/rejected/expired/failed)

## 2) Admin-API Error-Contract Konsolidierung

### Ziel
Alle relevanten 400/404 Pfade liefern jetzt konsistent:
- `ok: false`
- `error_code` (z. B. `bad_request`, `not_found`)
- `details` mit Kontext

### Geaenderte Dateien
- `adapters/admin-api/commander_routes.py`
- `adapters/admin-api/commander_api/operations.py`
- `adapters/admin-api/commander_api/containers.py`
- `adapters/admin-api/commander_api/secrets.py`
- `adapters/admin-api/commander_api/storage.py`

### Beispiele
- Approval 404 (`/approvals/{id}`, approve/reject): `error_code=not_found`
- Blueprint 404: `error_code=not_found`, `details.blueprint_id`
- Snapshot create ohne `volume_name`: `error_code=bad_request`
- Container exec ohne command: `error_code=bad_request`

## 3) Runtime Packaging / Deploy-Fix fuer Admin-API

### Problem
`jarvis-admin-api` crashte nach Restart mit:
`ModuleNotFoundError: No module named 'commander_api'`

### Fix
- Dockerfile ergaenzt:
  - `COPY adapters/admin-api/commander_api /app/commander_api`
- docker-compose Mount ergaenzt:
  - `./adapters/admin-api/commander_api:/app/commander_api:ro`

### Dateien
- `adapters/admin-api/Dockerfile`
- `docker-compose.yml`

## 4) WebUI - Container Commander UX/Design Refactor (OSX-inspiriert)

### `adapters/Jarvis/js/apps/terminal.js`

#### Dashboard-Startseite
- Neuer `Dashboard` Tab als Startseite.
- KPI-Leiste:
  - aktive Container
  - offene Approvals
  - Quota (RAM/CPU)
  - letzte Error-Count
- Timeline "Today" aus Audit.
- "Continue Working" mit zuletzt genutzten Blueprints/Volumes (localStorage).

#### Visual + Status-first UX
- Status-fokussierte Cards fuer Blueprints/Container.
- Sichtbare Status-Pills und vereinheitlichte Metadaten.

#### Blueprint UX
- Preset-Buttons:
  - Python
  - Node
  - DB
  - Shell
  - Web Scraper
- Inline-Live-Validierung fuer zentrale Felder.
- YAML Export erweitert:
  - Datei-Download
  - Clipboard-Copy
  - Vorschau im Log

#### Preflight + Trust
- Trust-Panel im Deploy-Preflight:
  - Network-Risk
  - Digest-Status
  - Signature-Status
  - Empfehlung

#### Container Detail Control Center
- Drawer als echtes Control-Center mit:
  - Logs
  - Stats
  - Events
- One-click Actions:
  - Refresh
  - Attach
  - Restart (ueber Blueprint)
  - Snapshot
  - Stop
- Auto-Refresh + Last-Update Anzeige.
- Einfache "suggested fix" Hinweise bei Fehlerbildern.

#### Terminal Power-Features
- Command Palette (`Ctrl/Cmd + K`) mit Kategorien:
  - Container
  - Storage
  - Approval
- History-Suche + "run again".
- Multi-Attach Session Tabs (schnelles Re-Attach auf mehrere Container).
- Copy-safe Logs (ANSI-strip) + Log-Download.

#### Approval Center Inbox Upgrade
- Priorisierung (Risk + TTL).
- Sticky Banner nur bei neu/eskaliert.
- Batch Approve/Reject ueber Selektion.
- Kontextkarte mit Risiko + Empfehlung.

#### Storage/Volume UX
- Workspace-Card Stil fuer Volumes.
- "In Use/Idle" Badges.
- Snapshot Compare (A/B, Delta Size, Source).
- Restore-Wizard mit Konflikt-Check + Confirm.

#### Activity / Audit Transparenz
- Live Activity Feed.
- Activity-Items klickbar -> Detail-Drawer.

### `adapters/Jarvis/static/css/terminal.css`
- OSX-inspiriertes Design-System mit:
  - glass panels
  - gradients
  - feinere typografische Hierarchie
- Neue Styles fuer:
  - Dashboard
  - Command Palette
  - History Strip
  - Shell Session Tabs
  - Trust Panel
  - Control Center Grid
  - Approval Context/Batches
  - Volume Compare
  - Activity Detail Drawer
- Mobile-Regeln fuer neue Layouts ergaenzt.

## 5) Neue/erweiterte Tests

### Frontend Contracts
- `tests/unit/test_frontend_terminal_runtime_ux_contract.py`
  - Dashboard Markup + Funktionen
  - Presets + Inline Validation + Export
  - Command Palette + History + Sessions + Log Export
  - Approval Inbox + Trust Panel
  - bestehende Runtime-UX Marker

### Backend/Contract Tests
- `tests/unit/test_container_commander_ws_stream_contract.py`
- `tests/unit/test_container_commander_approval_history_contract.py`
- `tests/unit/test_container_commander_engine_activity_contract.py`
- `tests/unit/test_commander_approval_error_contract.py`
- `tests/unit/test_commander_error_contract_remaining.py`
- `tests/unit/test_admin_api_commander_modular_mount_contract.py`

## 6) Validierung (heute)
- JS Syntax Check (`node --check`) bestanden.
- Mehrere fokussierte pytest-Suiten gruen (u. a. 28/28, 22/22, 7/7, 4/4 je nach Scope).
- Live API Smoketests erfolgreich (200 fuer Kernrouten).
- Live 400/404 Pfade nach Fix verifiziert: konsistentes `error_code` + `details`.
- WebSocket Smoketest erfolgreich (attach + strukturierte Fehlermeldung).

## 7) Offene optionale Folgearbeit
- Echte parallele PTY-Instanzen pro Shell-Tab (statt schnellem Re-Attach mit Session-Liste).
- Persistente Dashboard "continue" Daten serverseitig statt localStorage.
- E2E Browser-Test fuer neue Dashboard/Palette/Approval Batch Flows.

