# Container Manager Hardening Log (2026-03-08)

## Ziel
Container Manager vor Cronjob-Einführung stabilisieren (Timeouts, Race-Safety, Persistenz, Policy-Konsistenz).

## Schritte
- [x] Schritt 1: Hardening-Log anlegen
- [x] Schritt 2: Exec-Timeout wirklich enforce'n
- [x] Schritt 3: Runtime-State thread-safe machen (inkl. Quota-Reservation)
- [x] Schritt 4: Approval-Store persistent machen
- [x] Schritt 5: Namenskollisionen für Container/Volume vermeiden
- [x] Schritt 6: Approval-Policy für bridge/full konsistent machen
- [x] Schritt 7: Tests ergänzen + relevante Suiten laufen lassen

## Laufendes Protokoll
### Schritt 1 abgeschlossen
- Log-Datei angelegt.
- Reihenfolge für sichere Umsetzung fixiert.

### Schritt 2 abgeschlossen
- `container_commander/engine.py`:
  - neuer shell-basierter Timeout-Wrapper für `exec_in_container*`
  - Timeout wird jetzt deterministisch erzwungen (Exit-Code `124`)
  - strukturierte Antwort enthält bei `exec_in_container_detailed` zusätzlich `timed_out`

### Schritt 3 abgeschlossen
- `container_commander/engine.py`:
  - globaler Runtime-State-Lock (`RLock`) für `_active`, `_ttl_timers`, `_quota`
  - Quota-Race-Fix via atomare Reservation (`_reserve_quota`, `_release_*`, `_commit_*`)
  - `stop_container`, `cleanup_all`, `recover_runtime_state`, `get_container_stats`, `list_containers`, `get_quota` auf lock-sicheren Zugriff angepasst

### Schritt 4 abgeschlossen
- `container_commander/approval.py`:
  - persistenter Approval-Store (`APPROVAL_STORE_PATH`, default `/tmp/trion_approvals_store.json`)
  - Laden beim Modulstart (`_load_store()`), Speichern bei allen Mutationen (`_save_store_unlocked()`)
  - Expired-Approvals werden sauber archiviert und persistiert

### Schritt 5 abgeschlossen
- `container_commander/engine.py`:
  - neue kollisionsarme Suffix-Strategie (`_unique_runtime_suffix`)
  - Container-/Volume-Namen nutzen jetzt Millisekunden + UUID-Teil statt Sekunden-Timestamp

### Schritt 6 abgeschlossen
- Approval-Policy `bridge/full` vereinheitlicht über Flag:
  - `APPROVAL_REQUIRE_BRIDGE` (default: `true`)
  - umgesetzt in `container_commander/approval.py` und `container_commander/network.py`

### Schritt 7 abgeschlossen
- Neue Tests:
  - `tests/unit/test_container_manager_hardening_contract.py`
- Relevante Suiten:
  - `tests/unit/test_container_manager_hardening_contract.py`
  - `tests/unit/test_container_commander_approval_history_contract.py`
  - `tests/unit/test_commander_approval_error_contract.py`
  - `tests/unit/test_container_restart_recovery.py`
- Ergebnis: **31 passed**
- Zusatzcheck:
  - `py_compile` für geänderte Dateien: OK
