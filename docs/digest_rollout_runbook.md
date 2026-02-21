# Digest Pipeline — Operational Rollout Runbook

**Stand:** 2026-02-21 | Phase 8 Hardening merged
**Scope:** Stufenweise Aktivierung der Digest-Pipeline im Live-Betrieb, ohne Eingriff in `build_effective_context()`, Single Truth Channel oder Sync/Stream-Parität.

---

## Invarianten (vor JEDEM Stage-Wechsel prüfen)

| Invariante | Warum kritisch |
|---|---|
| `build_effective_context()` bleibt einziger Context-Entry-Point | Andere Einstiegspunkte würden Single Truth Channel brechen |
| Kein doppeltes Tool-Result (Single Truth Channel) | Doppelte Injection → falsche Budgets, Context-Pollution |
| Hard caps/budgets aktiv nach ALLEN Appends | Digest-Events sind auch Events — sie zählen gegen das Budget |
| Fail-closed Verhalten unverändert | Graph-Fallback ist `_try_save_to_graph` (fail-open nur dort) |
| Sync/Stream-Parität | Digest-Aktivierung darf kein Drift in Stream-Antworten erzeugen |

Kurzcheck vor Stage-Wechsel:
```bash
python -m pytest -q tests/unit/test_phase8_hardening.py::TestSyncStreamGuardrails -v
# → 2 passed
```

---

## Stage 0 — Deploy (alles OFF)

**Ziel:** Infrastruktur prüfen, API sichtbar, kein Digest-IO.

### Env-Werte
```env
DIGEST_ENABLE=false          # default — master-toggle bleibt aus
DIGEST_UI_ENABLE=false       # default — Panel ausgeblendet
DIGEST_RUN_MODE=off          # default — kein Worker-Loop
TYPEDSTATE_CSV_JIT_ONLY=false  # default (wird Stage 1 aktiviert)
```

### Verifikationskommandos
```bash
# 1. Container starten
docker-compose up -d jarvis-admin-api

# 2. Endpoint erreichbar
curl -s http://localhost:8200/api/runtime/digest-state | python3 -m json.tool

# 3. Sidecar-Service prüfen (läuft, tut nichts)
docker-compose up -d digest-worker
docker-compose logs digest-worker | tail -5
# Erwartet: [DigestWorker] mode=off — exiting with code 0
```

### Erwartete Telemetrie `/api/runtime/digest-state`
```json
{
  "jit_only": false,
  "daily_digest":  { "status": "never" },
  "weekly_digest": { "status": "never" },
  "archive_digest":{ "status": "never" },
  "locking":  { "status": "FREE", "owner": null, "stale": null },
  "catch_up": { "status": "never" },
  "jit":      { "trigger": null, "rows": null, "ts": null },
  "flags": {
    "enable": false,
    "daily":  false,
    "weekly": false,
    "archive":false,
    "ui":     false,
    "mode":   "off"
  }
}
```

### Go/No-Go
| Kriterium | Go | No-Go |
|---|---|---|
| HTTP 200 auf `/api/runtime/digest-state` | ✓ | → Admin-API nicht erreichbar: Port-Konflikt prüfen |
| `daily_digest.status == "never"` | ✓ | → State-Datei korrupt: `rm memory_speicher/digest_state.json` |
| `locking.status == "FREE"` | ✓ | → Stale Lock: `rm memory_speicher/digest.lock` |
| `digest-worker` endet sofort mit Code 0 | ✓ | → `restart: on-failure` verhindert Loop — OK |

### Rollback
```bash
# Nichts zu tun; defaults sind off
docker-compose stop digest-worker
```

---

## Stage 1 — JIT-Only (kein CSV-IO ohne Trigger)

**Ziel:** CSV-Events werden nur noch bei explizitem JIT-Trigger geladen. Verhindert unnötigen CSV-IO bei jedem Context-Build.

### Env-Änderungen
```env
TYPEDSTATE_CSV_JIT_ONLY=true     # NEU: strict JIT, kein load ohne trigger
DIGEST_FILTERS_ENABLE=true       # empfohlen: Zeitfenster-Filter aktiv
```

Zeitfenster-Defaults (können gelassen werden):
```env
JIT_WINDOW_TIME_REFERENCE_H=48   # 2 Tage (default)
JIT_WINDOW_FACT_RECALL_H=168     # 7 Tage (default)
JIT_WINDOW_REMEMBER_H=336        # 14 Tage (default)
```

### Verifikationskommandos
```bash
# Startup-Warning muss verschwinden (vorher geloggt wenn JIT_ONLY=false + DIGEST_ENABLE=true)
docker-compose logs admin-api | grep "JIT_ONLY"
# Erwartet: keine WARNING-Zeile mehr wenn DIGEST_ENABLE noch false

# Telemetrie-Check
curl -s http://localhost:8200/api/runtime/digest-state | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print('jit_only:', d['jit_only'])"
# Erwartet: jit_only: True

# Unit-Test: JIT strict
python -m pytest -q tests/unit/test_phase8_hardening.py::TestJITHardening -v
# → 5 passed
```

### Erwartete Telemetrie
```json
{
  "jit_only": true,
  "flags": { "enable": false, ... }
}
```

### Go/No-Go
| Kriterium | Go | No-Go |
|---|---|---|
| `flags.jit_only == true` | ✓ | → Env nicht übernommen: Service neu starten |
| Kein CSV-Load-Log ohne Trigger in admin-api Logs | ✓ | → `TYPEDSTATE_CSV_JIT_ONLY` nicht gesetzt |
| Sync/Stream-Gate 0 failures | ✓ | → Parität verletzt: Rollback Stage 1 |

### Rollback
```env
TYPEDSTATE_CSV_JIT_ONLY=false
```

---

## Stage 2 — Dedupe-Scope (default seit Hardening aktiv)

**Ziel:** Sicherstellen, dass Cross-Conversation-Dedupe-Key korrekt greift.

> **Hinweis:** `DIGEST_DEDUPE_INCLUDE_CONV=true` ist seit Phase 8 Hardening der Default. Dieser Stage ist ein expliziter Verifizierungsschritt, kein Flag-Toggle.

### Env-Werte (bereits default)
```env
DIGEST_DEDUPE_INCLUDE_CONV=true  # default seit Hardening-Commit 9
```

### Verifikationskommandos
```bash
python -m pytest -q tests/unit/test_phase8_hardening.py::TestJITHardening::test_dedupe_include_conv_default_true -v
# → 1 passed

python -m pytest -q tests/unit/test_phase8_hardening.py::TestJITHardening::test_dedupe_no_cross_conversation_collision -v
# → 1 passed
```

### Go/No-Go
| Kriterium | Go | No-Go |
|---|---|---|
| Beide Dedupe-Tests passed | ✓ | → Env override vorhanden: `unset DIGEST_DEDUPE_INCLUDE_CONV` |

### Rollback
```env
# Nur nötig wenn explizit auf false gesetzt
DIGEST_DEDUPE_INCLUDE_CONV=true  # default belassen
```

---

## Stage 3 — Daily Digest aktiv (Sidecar)

**Ziel:** Tägliche Kompression um 04:00 Europe/Berlin via Sidecar-Service. Catch-up bei Start.

### Env-Änderungen
```env
DIGEST_ENABLE=true               # Master-Toggle ON
DIGEST_DAILY_ENABLE=true         # Daily 04:00 aktiv
DIGEST_RUN_MODE=sidecar          # Sidecar-Worker (nicht inline)
DIGEST_CATCHUP_MAX_DAYS=7        # Max Rückwärts-Catch-up (default: 7)
DIGEST_MIN_EVENTS_DAILY=1        # Optional: mindestens 1 Event pro Tag
```

Empfohlen für Produktion:
```env
TYPEDSTATE_CSV_JIT_ONLY=true     # muss seit Stage 1 aktiv sein
DIGEST_DEDUPE_INCLUDE_CONV=true  # seit Stage 2 verifiziert
```

### Verifikationskommandos
```bash
# 1. Sidecar starten
docker-compose up -d digest-worker

# 2. Catch-up Log prüfen (erscheint kurz nach Start)
docker-compose logs -f digest-worker | grep -E "\[DigestWorker\]|\[DailyDigest\]|\[DigestCatchUp\]"
# Erwartet: [DigestWorker] run_once start, [DailyDigest] date=... status=ok|skip

# 3. State nach Catch-up
curl -s http://localhost:8200/api/runtime/digest-state | python3 -m json.tool

# 4. Lock-Prüfung während Run
curl -s http://localhost:8200/api/runtime/digest-state | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print('lock:', d['locking'])"
# Während Catch-up: status=LOCKED; danach: status=FREE

# 5. Gate
python -m pytest -q tests/unit/test_phase8_operational.py tests/unit/test_phase8_digest.py -q
# → alle passed, 0 failures
```

### Erwartete Telemetrie nach erstem erfolgreichen Run
```json
{
  "daily_digest": {
    "status":         "ok",
    "last_run":       "2026-02-21T04:00:xx+01:00",
    "input_events":   12,
    "digest_written": 3,
    "digest_key":     "d2...32chars",
    "reason":         null
  },
  "catch_up": {
    "status":      "ok",
    "missed_runs": 5,
    "recovered":   true,
    "generated":   5,
    "mode":        "cap"
  },
  "locking": { "status": "FREE", "owner": null, "stale": null }
}
```

### Go/No-Go
| Kriterium | Go | No-Go |
|---|---|---|
| `daily_digest.status == "ok"` nach Catch-up | ✓ | → Logs: `no_events`? → CSV-Pfad oder Trigger-Gate prüfen |
| `locking.status == "FREE"` nach Run | ✓ | → Stale Lock: siehe Known Failure Patterns |
| `catch_up.recovered == true` | ✓ | → Teilrecovery OK wenn weniger Events als CATCHUP_MAX_DAYS |
| `catch_up.mode` in `["cap", "full"]` | ✓ | → `"off"` → CATCHUP_MAX_DAYS=0 gesetzt? |
| Keine `TypeError` / `Exception` in Logs | ✓ | → Code-Fehler → Logs auswerten |
| Gate: 0 failures in test_phase8_operational.py | ✓ | → Regression, kein Rollout |

### Rollback
```env
DIGEST_ENABLE=false
DIGEST_DAILY_ENABLE=false
DIGEST_RUN_MODE=off
```
```bash
docker-compose stop digest-worker
# State-Datei bleibt; nächster Start führt erneuten Catch-up durch (idempotent)
```

---

## Stage 4 — Weekly Digest

**Ziel:** Wöchentliche Kompression aus Daily-Digests. Benötigt mindestens 1 Daily-Digest einer vollständigen ISO-Woche.

### Env-Änderungen
```env
DIGEST_WEEKLY_ENABLE=true        # Zusätzlich zu Stage 3
DIGEST_MIN_DAILY_PER_WEEK=1      # Optional: mindestens 1 Daily pro Woche
```

### Verifikationskommandos
```bash
docker-compose logs -f digest-worker | grep "\[WeeklyDigest\]"
# Erwartet nach 04:00: [WeeklyDigest] week=YYYY-Www conv=... status=ok|skip

curl -s http://localhost:8200/api/runtime/digest-state | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print(d['weekly_digest'])"

python -m pytest -q tests/unit/test_phase8_digest.py::TestWeeklyDigestArchiver -v
# → alle passed
```

### Erwartete Telemetrie
```json
{
  "weekly_digest": {
    "status":      "ok",
    "last_run":    "2026-02-21T04:00:xx",
    "digest_written": 1,
    "reason":      null
  }
}
```

### Go/No-Go
| Kriterium | Go | No-Go |
|---|---|---|
| `weekly_digest.status` in `["ok", "skip"]` | ✓ | `"error"` → Logs auswerten |
| `status == "skip"` erlaubt wenn | ISO-Woche noch nicht abgeschlossen | — |
| `status == "ok"` nach vollständiger Woche | ✓ | → Min-Threshold zu hoch? DIGEST_MIN_DAILY_PER_WEEK=0 |

### Rollback
```env
DIGEST_WEEKLY_ENABLE=false
```

---

## Stage 5 — Archive Digest

**Ziel:** Weekly-Digests die älter als 14 Tage sind, in den Graph archivieren. Erfordert Betrieb seit mindestens 14 Tagen.

### Env-Änderungen
```env
DIGEST_ARCHIVE_ENABLE=true       # Zusätzlich zu Stage 3+4
```

### Verifikationskommandos
```bash
docker-compose logs -f digest-worker | grep "\[ArchiveDigest\]"
# Erste 13 Tage: [ArchiveDigest] status=skip (keine alten Weeklys)
# Ab Tag 14+: [ArchiveDigest] date=... status=ok

curl -s http://localhost:8200/api/runtime/digest-state | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print(d['archive_digest'])"

python -m pytest -q tests/unit/test_phase8_digest.py::TestWeeklyDigestArchiver::test_run_archive_archives_old_weekly -v
# → 1 passed
```

### Erwartete Telemetrie (nach 14+ Tagen)
```json
{
  "archive_digest": {
    "status":      "ok",
    "last_run":    "2026-03-07T04:00:xx",
    "digest_written": 1,
    "reason":      null
  }
}
```

### Go/No-Go
| Kriterium | Go | No-Go |
|---|---|---|
| `archive_digest.status == "skip"` bis Tag 14 | ✓ | Erwartet, kein Fehler |
| `archive_digest.status == "ok"` ab Tag 14+ | ✓ | → Graph nicht erreichbar: `_try_save_to_graph` fail-open — Archive-CSV trotzdem geschrieben |

### Rollback
```env
DIGEST_ARCHIVE_ENABLE=false
```

---

## Stage 6 — Frontend Telemetry Panel

**Ziel:** Digest-Status-Panel im Advanced-Tab der UI sichtbar machen.

### Env-Änderungen
```env
DIGEST_UI_ENABLE=true            # Panel einblenden
```

### Verifikationskommandos
```bash
# API v2 Shape prüfen (wird von Frontend-Refresh genutzt)
curl -s http://localhost:8200/api/runtime/digest-state | \
  python3 -c "import json,sys; d=json.load(sys.stdin); \
  assert 'daily_digest' in d, 'Not v2'; print('v2 OK, keys:', list(d.keys()))"

python -m pytest -q tests/unit/test_phase8_hardening.py::TestFrontendTelemetryPanel -v
# → 5 passed (HTML panel, JS v2 keys, error handling)

# Browser: Advanced-Tab öffnen → Digest-Status-Panel sichtbar
# Panel zeigt: daily/weekly/archive Status-Cards, Locking-Card (FREE/LOCKED), Catch-up-Card
```

### Erwartete Telemetrie
Identisch Stage 3–5; Prüfpunkt ist UI-Rendering (kein Stacktrace in UI).

### Go/No-Go
| Kriterium | Go | No-Go |
|---|---|---|
| Panel sichtbar im Advanced-Tab | ✓ | → `DIGEST_UI_ENABLE` nicht gesetzt |
| Kein Stacktrace im Panel-Bereich | ✓ | → JS-Fehler: Browser-Console prüfen |
| `d.error` nicht gesetzt in refresh() | ✓ | → API-Fehler: Stage 3 Healthcheck wiederholen |
| V2 API-Keys vorhanden (`daily_digest`, `locking`) | ✓ | → `DIGEST_RUNTIME_API_V2=false`? → auf `true` setzen |

### Rollback
```env
DIGEST_UI_ENABLE=false
```

---

## Known Failure Patterns

### 1. Stale Lock (`locking.stale == true`)

**Symptom:** `locking.status == "LOCKED"`, `stale == true`, kein aktiver Worker-Prozess.

**Ursache:** Worker-Crash, SIGKILL, Container-Restart während Lock-Holding.

**Verifikation:**
```bash
curl -s http://localhost:8200/api/runtime/digest-state | \
  python3 -c "import json,sys; d=json.load(sys.stdin); l=d['locking']; \
  print('STALE' if l.get('stale') else 'OK', l)"
```

**Behebung:**
```bash
# Option A: Warten — nächster Run übernimmt Stale-Lock automatisch
# (Takeover via O_EXCL-Sentinel, serialisiert parallele Übernahmen)

# Option B: Manuell entfernen (wenn kein Worker läuft)
rm memory_speicher/digest.lock
# Nächster Worker-Start schreibt frischen Lock
```

**Prevention:** `DIGEST_LOCK_TIMEOUT_S=300` (default 5 min) — nach 5 Min gilt Lock als stale.

---

### 2. Catch-up Overrun

**Symptom:** Catch-up schreibt mehr Digests als erwartet, hoher CSV-IO nach Restart.

**Ursache:** `DIGEST_CATCHUP_MAX_DAYS` zu hoch oder nicht gesetzt; sehr lange Downtime.

**Verifikation:**
```bash
curl -s http://localhost:8200/api/runtime/digest-state | \
  python3 -c "import json,sys; d=json.load(sys.stdin); cu=d['catch_up']; \
  print('missed_runs:', cu.get('missed_runs'), 'mode:', cu.get('mode'))"
# mode=cap → CATCHUP_MAX_DAYS greift
# mode=full → unbegrenzt rückwärts
```

**Behebung:**
```env
DIGEST_CATCHUP_MAX_DAYS=3   # Reduzieren; 0 = catch-up komplett deaktivieren
```

**Prevention:** Standard-Deployment mit `DIGEST_CATCHUP_MAX_DAYS=7`.

---

### 3. JIT Noise (CSV-Load ohne sinnvollen Trigger)

**Symptom:** Viele CSV-Load-Logs ohne erkennbaren Trigger; hoher I/O.

**Ursache:** `TYPEDSTATE_CSV_JIT_ONLY=false` mit aktivem Digest-Pipeline.

**Verifikation:**
```bash
# Startup-Warning prüfen
docker-compose logs admin-api | grep "TYPEDSTATE_CSV_JIT_ONLY=false"
# Erscheint wenn: DIGEST_ENABLE=true UND JIT_ONLY=false

# JIT-Telemetrie
curl -s http://localhost:8200/api/runtime/digest-state | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print('jit:', d['jit'])"
# jit.trigger=null → load ohne Trigger
```

**Behebung:**
```env
TYPEDSTATE_CSV_JIT_ONLY=true   # Stage 1 aktivieren
```

---

### 4. Empty Digest (status=skip, reason=no_events oder insufficient_input)

**Symptom:** `daily_digest.status == "skip"`, `reason == "no_events"` oder `"insufficient_input"`.

**Ursache A — no_events:** Keine Events im CSV für die Ziel-Conversation/Datum.
**Ursache B — insufficient_input:** `DIGEST_MIN_EVENTS_DAILY > 0` und zu wenige Events.

**Verifikation:**
```bash
curl -s http://localhost:8200/api/runtime/digest-state | \
  python3 -c "import json,sys; d=json.load(sys.stdin); \
  print('reason:', d['daily_digest'].get('reason'))"

# CSV-Inhalt prüfen
wc -l memory_speicher/digest_store.csv
python3 -c "import csv; r=list(csv.DictReader(open('memory_speicher/digest_store.csv'))); \
  print(len(r), 'rows; actions:', set(x['action'] for x in r))"
```

**Behebung:**
```env
# Threshold senken oder deaktivieren
DIGEST_MIN_EVENTS_DAILY=0   # kein Minimum (default)

# Bei no_events: CSV-Pfad prüfen
DIGEST_STORE_PATH=memory_speicher/digest_store.csv  # default
```

---

## Operational SLO/Alerts (lightweight)

Täglich nach 04:30 Europe/Berlin diese 5 Metriken prüfen:

| # | Metrik | Sollwert | Alert-Schwelle |
|---|---|---|---|
| 1 | `daily_digest.status` | `"ok"` oder `"skip"` | `"error"` → PagerDuty/Log-Alert |
| 2 | `locking.status` | `"FREE"` nach Run | `"LOCKED"` + `stale=true` > 10 Min → Auto-remove Lock |
| 3 | `catch_up.missed_runs` | ≤ `CATCHUP_MAX_DAYS` (7) | > 7 → Downtime > 1 Woche, erhöhe CAP temporär |
| 4 | `jit.rows` (wenn trigger gesetzt) | > 0 bei bekannten JIT-Events | `0` bei `trigger != null` → CSV leer oder Filter zu eng |
| 5 | `weekly_digest.status` (Mo–So je Woche) | `"ok"` bis Wochende | `"skip"` nach vollständiger ISO-Woche → Daily-Threshold prüfen |

Minimales Alert-Skript:
```bash
# Einzeiler für Cron (täglich 04:30)
curl -sf http://localhost:8200/api/runtime/digest-state | \
  python3 -c "
import json,sys
d=json.load(sys.stdin)
errors=[]
if d['daily_digest'].get('status') == 'error': errors.append('DAILY_ERROR')
l=d['locking']
if l.get('status')=='LOCKED' and l.get('stale'): errors.append('STALE_LOCK')
if errors: print('ALERT:', errors); sys.exit(1)
print('SLO OK')
" || echo "DIGEST ALERT $(date)" >> /var/log/digest_alert.log
```

---

## One-Command Verification (vor Stage-Wechsel)

**Gate 1 — Guardrails (kein neuer Context-Injection-Kanal):**
```bash
python -m pytest -q tests/unit/test_phase8_hardening.py::TestSyncStreamGuardrails -v
# Soll: 2 passed, 0 failures
```

**Gate 2 — Phase 8 Combined Gate:**
```bash
python -m pytest -q \
  tests/unit/test_phase8_operational.py \
  tests/unit/test_phase8_findings.py \
  tests/unit/test_phase8_hardening.py \
  tests/unit/test_phase8_digest.py
# Soll: 207 passed, 0 failures
```

**Gate 3 — Full Unit Gate:**
```bash
python -m pytest -q \
  tests/unit/test_single_truth_channel.py \
  tests/unit/test_orchestrator_context_pipeline.py \
  tests/unit/test_context_cleanup_phase2.py \
  tests/unit/test_phase15_budgeting.py \
  tests/unit/test_container_restart_recovery.py \
  tests/unit/test_graph_hygiene.py \
  tests/unit/test_graph_hygiene_commit4.py \
  tests/unit/test_phase6_security.py \
  tests/unit/test_typedstate_v1_wiring.py \
  tests/unit/test_phase8_digest.py \
  tests/unit/test_phase8_operational.py \
  tests/unit/test_phase8_findings.py \
  tests/unit/test_phase8_hardening.py \
  tests/e2e/test_ai_pipeline_sync_stream.py \
  tests/e2e/test_memory_roundtrip.py \
  tests/e2e/test_golden_regression.py \
  tests/e2e/test_phase2_dedup.py \
  tests/e2e/test_phase3_typedstate.py \
  tests/e2e/test_phase4_recovery.py \
  tests/e2e/test_phase5_graph_hygiene.py
# Soll: ≥ 785 passed, 4 skipped, 0 failures
```

**Gate 4 — Ops-Skript Smoke:**
```bash
# (Admin-API muss laufen)
bash scripts/ops/check_digest_state.sh
# Soll: Exit 0 wenn FREE+healthy; Exit 1 wenn error/stale
```

---

## Schnellreferenz: Alle Digest-Flags

| Env-Variable | Default | Beschreibung |
|---|---|---|
| `DIGEST_ENABLE` | `false` | Master-Toggle — alle Features aus wenn false |
| `DIGEST_DAILY_ENABLE` | `false` | Daily 04:00 Kompression |
| `DIGEST_WEEKLY_ENABLE` | `false` | Weekly-Digest aus Daily-Digests |
| `DIGEST_ARCHIVE_ENABLE` | `false` | Archive nach 14 Tagen |
| `DIGEST_RUN_MODE` | `off` | `off` / `sidecar` / `inline` |
| `DIGEST_UI_ENABLE` | `false` | Frontend-Panel im Advanced-Tab |
| `DIGEST_RUNTIME_API_V2` | `true` | Flat V2 API-Shape |
| `TYPEDSTATE_CSV_JIT_ONLY` | `false` | Strict JIT — kein CSV ohne Trigger |
| `DIGEST_FILTERS_ENABLE` | `false` | Zeitfenster-Filter im JIT-Load |
| `DIGEST_DEDUPE_INCLUDE_CONV` | `true` | Cross-Conv-safe Dedupe-Key |
| `DIGEST_CATCHUP_MAX_DAYS` | `7` | Max Catch-up-Tage bei Start |
| `DIGEST_MIN_EVENTS_DAILY` | `0` | Min Events für Daily-Digest |
| `DIGEST_MIN_DAILY_PER_WEEK` | `0` | Min Dailys für Weekly-Digest |
| `DIGEST_LOCK_TIMEOUT_S` | `300` | Stale-Lock-Schwelle (Sekunden) |
| `DIGEST_KEY_VERSION` | `v1` | `v1` (compat) / `v2` (window bounds) |
| `DIGEST_JIT_WARN_ON_DISABLED` | `true` | Startup-Warning bei JIT=false |
| `JIT_WINDOW_TIME_REFERENCE_H` | `48` | Zeitfenster für time_reference |
| `JIT_WINDOW_FACT_RECALL_H` | `168` | Zeitfenster für fact_recall |
| `JIT_WINDOW_REMEMBER_H` | `336` | Zeitfenster für remember |
| `DIGEST_STATE_PATH` | `memory_speicher/digest_state.json` | Runtime-State-Datei |
| `DIGEST_LOCK_PATH` | `memory_speicher/digest.lock` | Lock-Datei |
| `DIGEST_STORE_PATH` | `memory_speicher/digest_store.csv` | Digest-Store-CSV |

---

*Dieses Runbook ist kanonisch für Phase 8 Hardening. Ops-Skript: `scripts/ops/check_digest_state.sh`.*
