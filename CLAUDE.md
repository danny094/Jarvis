# Claude Session Notes

## Stand: 2026-02-22 (C7 Package-Policy abgeschlossen)

---

## Abgeschlossene Phasen (Chronologie)

### TypedState V1 — Commit 1–3 ✅
- Commit 1: CSV Loader (`core/typedstate_csv_loader.py`), 51 Tests
- Commit 2: Deterministic Pipeline (6-Schritt: merge→normalize→dedupe→sort→correlate→apply), 53 Tests
- Commit 3: Renderer-Härte (`_build_now_bullets`, `_build_rules_bullets`, `_build_next_bullets`), 40 Tests

### Phase 5 — Graph Hygiene ✅ (2026-02-19)

**Ziel:** SQLite = Truth, Graph = Index — zentrales Hygiene-Pipeline für alle Blueprint-Graph-Queries.

**Commit 1 — `core/graph_hygiene.py` (neu):**
- `GraphCandidate` Dataclass: `blueprint_id`, `score`, `meta`, `content`, `updated_at`, `node_id`
- `_parse_candidate()`: nil-safe (try/except um float() + int())
- `dedupe_latest_by_blueprint_id()`: behält neueste Revision per blueprint_id (`updated_at`, `node_id`)
- `filter_against_sqlite_active_set()`: fail-closed default
- `apply_graph_hygiene()`: Full Pipeline mit Log-Markers

**Commit 2 — `core/blueprint_router.py`:**
- Inline-Filter durch `apply_graph_hygiene()` ersetzt
- fail-open (`_active_ids = None`) entfernt → fail-closed
- Trust-Level als `extra_filter`-Predicate

**Commit 3 — `core/context_manager.py` (`_search_blueprint_graph`):**
- Gleiche Hygiene-Pipeline, `content`-Feld in `GraphCandidate` hinzugefügt

**Commit 4 — Delete-Konsistenz:**
- `blueprint_store._sync_single_blueprint_to_graph()`: `updated_at` in Metadata
- `blueprint_store.sync_blueprints_to_graph()`: `updated_at` in Bulk-Sync-Metadata (Finding #1)
- `blueprint_store.remove_blueprint_from_graph()`: neue Tombstone-Funktion
- `commander_routes.api_delete_blueprint`: ruft Tombstone async (non-critical)
- `tools/reconcile_graph_index.py`: neues Standalone-Reconcile-Script

**Commit 5 — Tests:**
- `tests/unit/test_graph_hygiene.py`: 39 Tests (6 Klassen)
- `tests/unit/test_graph_hygiene_commit4.py`: 23 Tests, 5 Skips (5 Klassen — Findings #1–#3)

**Container-Restart-Recovery Tests (Phase 4 Fix):**
- `tests/unit/test_container_restart_recovery.py`: 21 Tests — sys.modules mock-Strategie

### Phase 6 — Security & Hardening ✅ (2026-02-20)

**P6-A — Signature Verify Backend:**
- `config.py`: `get_signature_verify_mode()` + `SIGNATURE_VERIFY_MODE` (off|opt_in|strict)
- `container_commander/trust.py`: `verify_image_signature()` — echte Implementierung statt Stub
  - `_detect_no_signature()`: unterscheidet "absent" von "invalid"
  - `_try_verify()`: cosign → notation Fallback-Kette; TimeoutExpired, FileNotFoundError behandelt
  - Modusentscheidung: off=pass; opt_in=absent→allow/invalid→reject; strict=beides→reject
  - Strukturiertes Logging: `[Signature] VERIFIED/BLOCK/opt_in allow`

**P6-B — XSS/Markdown Sanitizing Frontend:**
- Neu: `adapters/Jarvis/static/js/sanitize.js` — shared `TRIONSanitize.sanitizeHtml()`
  - DOMPurify (wenn geladen) oder DOM-Fallback; `rel=noopener noreferrer` für `target=_blank`
  - Schlägt `<script>`, `<iframe>`, `<object>`, on*-Attrs, `javascript:/vbscript:/data:text/html` tot
- `workspace.js`: `renderMarkdown()` nutzt TRIONSanitize → DOMPurify → DOM-Fallback (mit noopener)
- `protocol.js`: `sanitizeHtml()` lokal + `marked.parse()` überall gewrappt
  - Fix: Cancel-Button-Handler kein inline-`onclick` mit Template-Literal mehr (XSS-Vektor entfernt)

**P6-C — REST Deploy Parity:**
- `chat.js`: `conversation_id` wird bei `protocol/append` mitgesendet (kein silent drop)
- `protocol_routes.py` `/append`: nimmt `conversation_id` + `session_id` an, gibt sie in Response zurück
- `commander_routes.py` `/containers/deploy`: loggt + forwarded `conversation_id`/`session_id`; echot sie bei `PendingApprovalError`-Response zurück

**P6-D — Tests + Gate + Dataset:**
- `tests/unit/test_phase6_security.py`: 75 Tests (4 Klassen P6-A, 3 Klassen P6-B, 3 Klassen P6-C, 4 Klassen Wiring/Runtime)
- `tests/datasets/cases/core_phase6_security.yaml`: 16 Cases (Phase 6, valid: 36/36 gesamt)
- `scripts/test_gate.sh`: P6-Security-Sektion in Full Gate ergänzt

### AI Test Stack A–G ✅ (2026-02-19)

**Commit A — Harness Basis** (`tests/harness/`):
- `types.py`: `HarnessInput`, `HarnessResult`, `StreamEvent` Dataclasses
- `assertions.py`: `assert_contains`, `assert_not_contains`, `assert_event`, `assert_context_markers`, +3
- `runner.py`: `HarnessRunner` (sync+stream), `normalize_response()` (timestamps/UUIDs/dates/epochs maskiert)

**Commit B — Provider Abstraktion** (`tests/harness/providers/`):
- `ai_client.py`: `AIProvider` Protocol + `get_provider("auto"|"mock"|"live")`
- `mock_provider.py`: Keyword-Library + Hash-Fallback, `temperature=0`-äquivalent
- `live_provider.py`: Ollama-HTTP, `temperature=0`, `seed=42`, max 2 Retries — opt-in via `AI_TEST_LIVE=1`

**Commit C — Dataset** (`tests/datasets/`):
- `schema/test_case.schema.json`: JSON Schema draft-07, Pflichtfelder: id/phase/title/mode/input/expected/tags
- `cases/core_phase0_5.yaml`: 20 Test-Cases, Phase 0–5 + cross-phase Memory-Roundtrip
- `tools/validate_test_dataset.py`: Validator, exit 1 bei Fehler
- `tests/datasets/README.md`

**Commit D — Golden Regression** (`tests/golden/`, `tests/harness/golden.py`):
- 7 Golden-Snapshots (p0/p2/p3/p5), Normalizer vorgeschaltet
- `AI_UPDATE_GOLDEN=1` = bewusstes Update; `AI_GOLDEN_DIR=...` = alternativer Pfad (bei ACL)
- `tests/e2e/test_golden_regression.py`: 14 Tests

**Commit E — E2E AI-Pipeline**:
- `tests/e2e/test_ai_pipeline_sync_stream.py`: Sync/Stream-Parität, Marker-Präsenz, Error-Handling (26 Tests)
- `tests/e2e/test_memory_roundtrip.py`: Store→Recall, Isolation, Determinismus (10 Tests)

**Commit F — Phase-spezifische E2E** (je 3–5 Invarianten + Negative Cases + Dataset-Durchlauf):
- `test_phase2_dedup.py`: Single Truth Channel, Dedup-Pipeline (11 Tests)
- `test_phase3_typedstate.py`: NOW-Block, CompactContext, Source-Weights (14 Tests)
- `test_phase4_recovery.py`: Restart, TTL-Rearm, Source Inspection (11 Tests)
- `test_phase5_graph_hygiene.py`: Dedupe, Latest-Revision, SQLite-Fail-Closed, Pipeline-Counts (22 Tests)

**Commit G — CI Gate** (`scripts/test_gate.sh`):
- Quick Gate: dataset + harness smoke + golden smoke (`< 5 min`)
- Full Gate: alle Unit + alle E2E
- Nightly Live Gate: nur bei `AI_TEST_LIVE=1`

### TypedState V1 — Commit 4 ✅ (2026-02-20)
- Shadow/Active Wiring: `TYPEDSTATE_MODE=shadow` → Diff-Log, `=active` → V1-Render
- `_log_typedstate_diff()`, `format_typedstate_v1()` in `core/context_cleanup.py`
- `context_manager.build_small_model_context` mit `trigger: Optional[str]` + Modusbranch
- 39 Tests in `tests/unit/test_typedstate_v1_wiring.py`

### Phase 8 — Digest Pipeline ✅ (2026-02-20)

**Commit A — Config/Flags:**
- 9 neue Getter in `config.py`: `get_digest_enable`, `get_digest_daily_enable`, `get_digest_weekly_enable`, `get_digest_archive_enable`, `get_digest_tz`, `get_digest_store_path`, `get_typedstate_csv_jit_only`, `get_digest_filters_enable`, `get_digest_dedupe_include_conv`
- Alle defaults OFF/safe

**Commit B — JIT Trigger Gating:**
- `maybe_load_csv_events(trigger=None)` mit `_JIT_VALID_TRIGGERS = {"time_reference", "remember", "fact_recall"}`
- `JIT_ONLY=true` + ungültiger Trigger → leere Liste
- Trigger-Propagation: `orchestrator._build_effective_context` → `_get_compact_context` → `build_small_model_context`

**Commit C — CSV Filter:**
- `load_csv_events(start_ts, end_ts, conversation_id, actions)` — alle optional, Filter nach Row-Load

**Commit D — Dedupe-Härtung:**
- `DIGEST_DEDUPE_INCLUDE_CONV=true` → Key = `"{conv_id}:{ev_type}:{ev_hash}"` (Cross-Conv safe)

**Commit E — Digest Event-Typen:**
- `_apply_event` in `context_cleanup.py`: `daily_digest` → DAILY_DIGEST, `weekly_digest` → WEEKLY_DIGEST, `archive_digest` → ARCHIVE_DIGEST — alle fail-closed

**Commit F — Daily Scheduler (neue Dateien):**
- `core/digest/__init__.py`
- `core/digest/keys.py`: `make_source_hash` (16-char), `make_daily_digest_key`, `make_weekly_digest_key`, `make_archive_digest_key` (je 32-char, sha256)
- `core/digest/store.py`: `DigestStore` — CSV-Persistenz, `exists()`, `list_by_action()`, `write_daily/weekly/archive()`
- `core/digest/daily_scheduler.py`: `DailyDigestScheduler` — ZoneInfo Berlin TZ, catch-up, idempotent

**Commit G — Weekly + Archive:**
- `core/digest/weekly_archiver.py`: `WeeklyDigestArchiver` — `run_weekly`, `run_archive`, Graph-Fallback (fail-open), 14-Tage-Threshold

**Commit H — Tests + Gate:**
- `tests/unit/test_phase8_digest.py`: 85 Tests — P8-A/B/C/D/E/F/G + Trigger-Parität
- Bug fix: `write_archive` fügt `"digest_key": archive_key` in parameters hinzu → `exists()` erkennt Archive korrekt

### Phase 8 Operativ ✅ (2026-02-20)

**Punkt 1 — Runtime State + Locking:**
- `core/digest/runtime_state.py`: JSON-State (atomic via temp+rename), `get_state()`, `update_cycle()`, `update_catch_up()`, `update_jit()`
- `core/digest/locking.py`: File-Lock mit owner+pid+timeout, stale-takeover, `DigestLock` Context-Manager
  - Fresh lock: `O_CREAT|O_EXCL` (atomic, TOCTOU-frei)
  - Stale takeover: O_EXCL-Sentinel `.takeover` serialisiert parallele Takeover-Versuche (Finding 1-B)
- Config: `get_digest_state_path`, `get_digest_lock_path`, `get_digest_lock_timeout_s` (default 300s)

**Punkt 2 — Scheduler Worker:**
- `core/digest/worker.py`: `DigestWorker` — `run_loop()` (blocking, 04:00 TZ), `run_once()` (daily→weekly→archive, Lock-geschützt)
- `scripts/digest_worker.py`: Standalone-Einstiegspunkt für Sidecar
- Config: `get_digest_run_mode` (off|sidecar|inline, default off)

**Punkt 3 — Catch-up begrenzen:**
- `daily_scheduler.run_catchup`: `DIGEST_CATCHUP_MAX_DAYS` (default 7), `max_days=0` → skip
- Cap: `first_date = max(event_first_date, yesterday - timedelta(days=max_days-1))`

**Punkt 4 — Auto-Conversation-List:**
- `daily_scheduler.run(None)` → `_derive_conversation_ids()` → unique IDs aus CSV
- Kein externer conv_id-Input nötig

**Punkt 5 — Input-Qualität:**
- `DIGEST_MIN_EVENTS_DAILY` (default 0): Skip daily wenn events < min
- `DIGEST_MIN_DAILY_PER_WEEK` (default 0): Skip weekly wenn daily_keys < min
- Logging: `status=skip reason=insufficient_input`

**Punkt 6 — Idempotenz-Key (bereits in H gefixt):**
- `write_archive` enthält `"digest_key": archive_key` in parameters → `exists()` findet Archive korrekt

**Punkt 7 — JIT-only strikt:**
- `maybe_load_csv_events` erweitert um `conversation_id`, `start_ts`, `end_ts`, `actions`
- JIT_ONLY=true + trigger=None → strikt kein CSV-IO
- JIT-Telemetrie: `runtime_state.update_jit(trigger, rows)` nach jedem Load

**Punkt 8 — Zeitfenster-Filter:**
- `DIGEST_FILTERS_ENABLE=true` + trigger → window:
  - `time_reference` → `JIT_WINDOW_TIME_REFERENCE_H` h (default 48)
  - `fact_recall`    → `JIT_WINDOW_FACT_RECALL_H` h (default 168 / 7d)
  - `remember`       → `JIT_WINDOW_REMEMBER_H` h (default 336 / 14d)

**Punkt 9 — Runtime API:**
- `adapters/admin-api/runtime_routes.py`: `GET /api/runtime/digest-state`
  - Response: `{state, flags, lock}` — stabile Struktur auch ohne ersten Run
- In `main.py` registriert; `docker-compose.yml` mount: `runtime_routes.py:/app/runtime_routes.py:ro`

**Punkt 10 — Frontend-Panel:**
- `index.html`: `div#digest-status-panel` (hidden by default, Feature-Flag `DIGEST_UI_ENABLE`)
  - Cycle-Cards (Daily/Weekly/Archive), Flag-Chips, Lock-Status, JIT-Telemetrie, Catch-up-Info
- `settings.js`: `window.DigestUI` — `init()` (Panel-Freischaltung via Flag), `refresh()` (fetch + Render)
  - `setupDigestUIHandlers()` — Auto-load beim Advanced-Tab-Klick

**Punkt 11 — Sidecar im Compose:**
- Service `digest-worker` in `docker-compose.yml`: gleiche Dockerfile, `command: python /app/scripts/digest_worker.py`
- Shared volume: `./memory_speicher:/app/memory_speicher` (State/Store/Lock cross-service)
- Default: `DIGEST_RUN_MODE=off` / `DIGEST_ENABLE=false` → null behaviour

**Punkt 12 — Rollout-Phasen (Gates):**
- Stufe a: Endpoint + UI ON, alles OFF → `docker-compose up digest-worker` (läuft, tut nichts)
- Stufe b: `DIGEST_ENABLE=true` + `TYPEDSTATE_CSV_JIT_ONLY=true` → JIT-Only aktiv
- Stufe c: `DIGEST_DAILY_ENABLE=true` + `DIGEST_RUN_MODE=sidecar` → Daily 04:00
- Stufe d: `DIGEST_WEEKLY_ENABLE=true` → Weekly-Digest nach Daily
- Stufe e: `DIGEST_ARCHIVE_ENABLE=true` → Archive nach 14 Tagen
- Rollback je Stufe: Flag-Disable, kein Code-Revert nötig

### Phase 8 Operational Hardening ✅ (2026-02-20)

**15-Item Hardening (Commits 1–14):**

**Commit 1 — Baseline Tag:** `git tag phase8-ops-hardening-start`

**Commit 2 — Double-Start Guard (Item 2):**
- `main.py`: `threading.enumerate()` check vor Inline-Thread-Start
- Wenn `digest-inline` bereits alive → Warning + Skip
- Log: `[DigestWorker] inline already running — skip double-start`
- Log: `[DigestWorker] inline mode starting — mutual exclusion via DigestLock`

**Commit 3 — Crash-Loop-Schutz (Item 3):**
- `docker-compose.yml`: `digest-worker` → `restart: on-failure` (war `unless-stopped`)
- Wenn `DIGEST_RUN_MODE=off`: Script endet mit Code 0 → kein Restart-Loop

**Commit 4 — Runtime State Schema v2 (Item 4):**
- `core/digest/runtime_state.py`: `schema_version=2`
- Neue Cycle-Felder: `reason: str|null`, `retry_policy: str|null`
- Neues `catch_up`: `missed_runs`, `recovered`, `generated`, `mode`
- Strukturierter `jit`-Block: `{trigger, rows, ts}` statt flat `jit_last_*`
- Migration v1→v2: `_migrate_state()` — idempotent bei jedem Read
- Rückwärtskompatibel: alte State-Dateien werden beim ersten Read migriert

**Commits 5+6 — Strukturierte Scheduler-Summaries + Catch-up-Semantik (Items 5, 6):**
- `daily_scheduler.run()` → `{written, input_events, skipped, reason, conversation_ids, catch_up}`
- `daily_scheduler.run_catchup()` → `{written, days_examined, missed_runs, recovered, generated, mode}`
  - `mode="cap"` wenn `DIGEST_CATCHUP_MAX_DAYS` greift; `"full"` sonst
- `weekly_archiver.run_weekly()` → `{written, skipped, reason}`
- `weekly_archiver.run_archive()` → `{written, skipped}`
- `worker.py`: `_extract_count(result)`, `_extract_field(result, field)` — backward-compat mit int
- `run_once()` propagiert `input_events`, `reason` an `update_cycle()`
- `run_once()` propagiert `missed_runs`, `recovered`, `generated`, `mode` an `update_catch_up()`

**Commit 7 — API Contract v2 + Lock Transparency (Items 7, 12):**
- `config.py`: `get_digest_runtime_api_v2()` (default True, `DIGEST_RUNTIME_API_V2`)
- `adapters/admin-api/runtime_routes.py`: V2 flat shape:
  ```json
  { "jit_only": bool, "daily_digest": {...}, "weekly_digest": {...},
    "archive_digest": {...}, "locking": {"status": "FREE|LOCKED", "owner",
    "since", "timeout_s", "stale"}, "catch_up": {...}, "jit": {...}, "flags": {...} }
  ```
- V1 legacy: `DIGEST_RUNTIME_API_V2=false` → alter `{state, flags, lock}` Shape
- `_build_locking(lock_info)`: `status=FREE/LOCKED`, `stale` per Age-Check

**Commit 8 — JIT-Härtung + Startup-Warning (Item 8):**
- `config.py`: `get_digest_jit_warn_on_disabled()` (default True)
- `main.py` Startup: Warning wenn `DIGEST_ENABLE=true` und `JIT_ONLY=false`
- `typedstate_csv_loader.py`: Once-per-process Warning bei Load ohne Trigger

**Commit 9 — Dedupe Default True (Item 9):**
- `config.py`: `get_digest_dedupe_include_conv()` default `"false"` → `"true"`

**Commit 10 — Digest Key V2 (Item 10):**
- `core/digest/keys.py`: `make_daily_digest_key_v2`, `make_weekly_digest_key_v2`, `make_archive_digest_key_v2`, `_iso_week_bounds(iso_week)`
- `config.py`: `get_digest_key_version()` (default `"v1"`, `DIGEST_KEY_VERSION`)
- `daily_scheduler.py`, `weekly_archiver.py`: v2-Key wenn konfiguriert
- `store.py`: `write_daily/weekly()` nimmt `window_start=None, window_end=None` kwargs

**Commit 11 — Lock-Status-Funktion (Item 11):**
- `core/digest/locking.py`: `get_lock_status() → {status, owner, since, timeout_s, stale}`

**Commit 12 — Frontend Telemetry Panel v2 (Item 13):**
- `index.html`: `#digest-locking-card` mit `#digest-lock-status`, Catch-up Detail-Zeile
- `settings.js`: `_lockingCard(locking)`, `_catchUpCard(cu)` — neue Helfer
- `refresh()`: V2-Erkennung via `d.daily_digest !== undefined`, V1-Fallback
- Fehlermeldung via `d.error` statt unkontrollierter throw

**Commit 13 — Guardrail Tests (Item 14):**
- `test_phase8_hardening.py`: 47 neue Tests für Commits 2–13
- Guardrails: Phase-8-Module rufen kein `build_effective_context` auf, importieren nicht `layers.output`

**Commit 14 — Rollout-Runbook (Item 15):** Dieses Dokument.

**Gate nach Hardening:** 592 passed, 4 skipped, 0 failures (Unit-Gate ohne E2E)

---

## Blocking Gate (täglich prüfen)

**Stand: 2026-02-24 — 995 passed (Unit-Gate), 4 skipped, 0 failures (Scope 3.1 Embedding Policy; +54 Tests: test_scope31_embedding_policy)**

### Quick Gate

```bash
python tools/validate_test_dataset.py
# Soll: Dataset OK: 36/36 case(s) valid.

python -m pytest -q \
  tests/e2e/test_ai_pipeline_sync_stream.py \
  tests/e2e/test_golden_regression.py::TestNormalizerStability \
  tests/e2e/test_golden_regression.py::TestGoldenPhase0
# Soll: alle passed, 0 failures, < 5s
```

### Full Gate (Unit-Tests)

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
  tests/unit/test_skill_detail_contract.py \
  tests/unit/test_typedstate_skills.py \
  tests/unit/test_single_truth_skill_context_sync_stream.py \
  tests/unit/test_single_control_authority.py \
  tests/unit/test_package_endpoint_contract.py \
  tests/unit/test_skill_package_policy.py \
  tests/unit/test_embedding_resolver.py \
  tests/unit/test_scope31_embedding_policy.py \
  tests/e2e/test_ai_pipeline_sync_stream.py \
  tests/e2e/test_memory_roundtrip.py \
  tests/e2e/test_golden_regression.py \
  tests/e2e/test_phase2_dedup.py \
  tests/e2e/test_phase3_typedstate.py \
  tests/e2e/test_phase4_recovery.py \
  tests/e2e/test_phase5_graph_hygiene.py \
  -q
# Soll: ≥ 1000 passed (Unit-Gate), 4 skipped, 0 failures
```

Oder via Shell-Skript:
```bash
./scripts/test_gate.sh           # Quick Gate
./scripts/test_gate.sh full      # Full Gate
./scripts/test_gate.sh live      # Nightly (AI_TEST_LIVE=1 erforderlich)
```

### Nightly Live Gate (opt-in)

```bash
export AI_TEST_LIVE=1
export AI_TEST_BASE_URL=http://localhost:11434
export AI_TEST_MODEL=qwen2.5:14b    # optional
./scripts/test_gate.sh live
```

**Test-Scope (17 Dateien):**

| Datei | Tests | Scope |
|---|---|---|
| `test_single_truth_channel.py` | 45 | TypedState Single-Truth-Channel |
| `test_orchestrator_context_pipeline.py` | 59 | Orchestrator Context-Pipeline |
| `test_context_cleanup_phase2.py` | 160 | Context-Cleanup Phase 2 |
| `test_phase15_budgeting.py` | 17+1s | Phase 1.5 Budgeting |
| `test_container_restart_recovery.py` | 21 | Container Restart Recovery |
| `test_graph_hygiene.py` | 39 | Graph Hygiene Core-Pipeline |
| `test_graph_hygiene_commit4.py` | 23+5s | Delete-Konsistenz, Tombstone, Reconcile |
| `test_phase6_security.py` | 75 | Phase 6 Security (P6-A/B/C + Wiring) |
| `test_typedstate_v1_wiring.py` | 39 | TypedState V1 Shadow/Active Wiring |
| `test_phase8_digest.py` | 85 | Phase 8 Digest Pipeline (A–G) |
| `test_phase8_operational.py` | 51 | Phase 8 Operativ (Runtime/Lock/Worker/Catchup/JIT/API) |
| `test_phase8_findings.py` | 23 | Phase 8 Findings (Finding 1-A/B + 2–5) |
| `test_phase8_hardening.py` | 47 | Phase 8 Hardening (Commits 2–13: API/Keys/Frontend/Guardrails) |
| `test_skill_detail_contract.py` | 21 | C1 Skill-Detail-Contract (GET /v1/skills/{name}, channel param, flag) |
| `test_typedstate_skills.py` | 79 | C5 TypedState Skills-Entity (normalize/dedupe/top_k/budget/render/pipeline) |
| `test_single_truth_skill_context_sync_stream.py` | 34 | C6 Single-Truth-Channel (renderer routing, no echo, sync/stream parity) |
| `test_single_control_authority.py` | 23 | C4.5 Single Control Authority (echte server.py-Tests, strict validation passed+source, fail-closed, rollback) |
| `test_package_endpoint_contract.py` | 25 | C3 Package-Endpoint-Contract (/v1/packages GET+POST) |
| `test_skill_package_policy.py` | 21 | C7 Package-Policy (allowlist_auto, pending_approval, manual_only rollback, fail-closed) |
| `test_embedding_resolver.py` | 13 | Embedding Model Resolution (precedence, freeze-guard, sql-memory TTL cache) |
| `test_scope31_embedding_policy.py` | 54 | Scope 3.1 Embedding Policy (contract, router matrix, logging, metrics, regression) |
| `test_ai_pipeline_sync_stream.py` | 26 | Sync/Stream Parität + Marker |
| `test_memory_roundtrip.py` | 10 | Memory Store→Recall |
| `test_golden_regression.py` | 14 | Golden Snapshots + Normalizer |
| `test_phase2_dedup.py` | 11 | Phase 2 Single Truth Channel |
| `test_phase3_typedstate.py` | 14 | Phase 3 TypedState/CompactContext |
| `test_phase4_recovery.py` | 11 | Phase 4 Restart Recovery |
| `test_phase5_graph_hygiene.py` | 22 | Phase 5 Graph Hygiene |

---

## Digest Pipeline — Rollout Runbook

**Vollständiges Runbook (Stage 0–6, Go/No-Go, Failure Patterns, SLO, Gates):**
→ [`docs/digest_rollout_runbook.md`](docs/digest_rollout_runbook.md)

**Ops-Health-Skript:** `scripts/ops/check_digest_state.sh` — kompakte Status-Ausgabe + Exit 1 bei error/stale-lock.

**Kurzübersicht der 7 Stufen:**

| Stage | Flag-Änderung | Health-Check |
|---|---|---|
| 0 | alle defaults (off) | `GET /api/runtime/digest-state` → HTTP 200, `locking.status=FREE` |
| 1 | `TYPEDSTATE_CSV_JIT_ONLY=true` | `flags.jit_only=true` |
| 2 | `DIGEST_DEDUPE_INCLUDE_CONV=true` (default) | Dedupe-Test passed |
| 3 | `DIGEST_ENABLE=true` + `DIGEST_DAILY_ENABLE=true` + `DIGEST_RUN_MODE=sidecar` | `daily_digest.status=ok` nach Catch-up |
| 4 | `DIGEST_WEEKLY_ENABLE=true` | `weekly_digest.status=ok\|skip` |
| 5 | `DIGEST_ARCHIVE_ENABLE=true` | `archive_digest.status=ok` nach 14+ Tagen |
| 6 | `DIGEST_UI_ENABLE=true` | Panel sichtbar, kein Stacktrace |

Rollback je Stufe: Flag auf Standardwert → kein Code-Revert nötig.
Stale Lock: `rm memory_speicher/digest.lock` (nächster Worker-Start übernimmt automatisch).

## C4.5 Single Control Authority ✅ (2026-02-22)

**Ziel:** skill-server = einzige Decision-Authority; tool-executor = reiner Side-Effect-Owner.

**Änderungen (5 Dateien + docker-compose + Tests):**

- **`config.py`**: `get_skill_control_authority()` — `SKILL_CONTROL_AUTHORITY=skill_server` (default) | `legacy_dual` (Rollback)
- **`tool_executor/api.py`**:
  - `CreateSkillRequest` + `control_decision: Optional[Dict]` Feld
  - `create_skill` endpoint: bei `skill_server` → kein `get_mini_control().process_request()` Aufruf
  - **Strict validation** (Finding 3 Fix): `action` in (approve|warn) + `passed is True` + `source == "skill_server"` — alle drei Checks fail-closed mit `rejected_by_authority`
  - `missing_authority_decision` bei fehlendem/leerem Payload
  - Legacy `legacy_dual` Path bleibt vollständig als Rollback-Pfad
- **`mcp-servers/skill-server/server.py`** — `handle_create_skill()`:
  - Package-Check bleibt
  - **Neu**: CIM-Validierung via `_ctrl.process_request()` — BLOCK → sofortiger Return, Executor wird nicht aufgerufen
  - APPROVE/WARN → `control_decision` Dict gebaut (`source="skill_server"`, `policy_version="1.0"`) + an `skill_manager.create_skill` weitergegeben
- **`mcp-servers/skill-server/mini_control_layer.py`** — `_install_skill()`:
  - Neuer Param `control_decision: Optional[Dict] = None`
  - In `process_autonomous_task()` nach Validierung: `_cd` aus ValidationResult gebaut → an `_install_skill()` weitergegeben
- **`mcp-servers/skill-server/skill_manager.py`** — `create_skill()`:
  - `control_decision` Pass-through zum Executor-Payload ergänzt
- **`docker-compose.yml`**: `SKILL_CONTROL_AUTHORITY=skill_server` für `skill-server` + `tool-executor`
- **`tests/unit/test_single_control_authority.py`**: 23 Tests (7 Klassen)
  - **Parts 1+2** laden jetzt echtes `server.py` (Finding 4 Fix) — testen `handle_create_skill` direkt
  - **Part 4** um 2 Tests erweitert: `passed=False` → rejected, falscher `source` → rejected

**DoD-Check:**
- ✅ Kein divergentes Policy-Resultat mehr (ein Authority-Punkt)
- ✅ Executor führt nur Side-Effects aus (kein CIM-Aufruf in `skill_server` mode)
- ✅ Rollback per `SKILL_CONTROL_AUTHORITY=legacy_dual` ohne Code-Revert
- ✅ 21 neue Tests + 124 Regression-Tests passed

### C7 — Package-Policy as Event/State ✅ (2026-02-22)

**Ziel:** Non-allowlisted packages NEVER auto-installed. Fail-closed. Rollback per Env.

**Geänderte Dateien:**
- **`config.py`**: `get_skill_package_install_mode()` — `"allowlist_auto"` (default) | `"manual_only"` (rollback)
- **`docker-compose.yml`**: `SKILL_PACKAGE_INSTALL_MODE=allowlist_auto` für `skill-server`
- **`mcp-servers/skill-server/mini_control_layer.py`**:
  - `_get_package_allowlist()`: `GET /v1/packages` → `allowlist` set; fail-closed (empty on error)
  - `_auto_install_packages()`: `POST /v1/packages/install` pro Paket; fail-closed
  - Step 3.5 in `process_autonomous_task()`: classify → `non_allowlisted` → `pending_package_approval`; `allowlisted` → auto-install
- **`mcp-servers/skill-server/server.py`** — `handle_create_skill()`:
  - `manual_only`: bisheriges `needs_package_install`-Verhalten erhalten
  - `allowlist_auto`: classify via `_get_package_allowlist()` → any non-allowlisted → `pending_package_approval` response (mit `needs_package_install=True` Compat-Field)
  - Only all-allowlisted → `_auto_install_packages()` → weiter zu CIM+create
- **`tests/unit/test_skill_package_policy.py`**: 21 Tests (7 Klassen — Config/NonAllowlisted/Allowlisted/Mixed/ManualOnly/FailClosed/SourceInspection)
- **`tests/unit/test_single_control_authority.py`**: C7 Additions in `_build_server_mocks()` + aktualisierter Docstring

**Finding-Fixes (Codex-Review):**
- **Finding 1** — `orchestrator.py` `_build_tool_result_card()`: `_entry_type` jetzt dynamisch — erkennt `event_type/action_taken == "approval_requested"|"pending_package_approval"` → speichert `entry_type="approval_requested"` + `skill_name/missing_packages` → `context_cleanup` befüllt `pending_approvals`
- **Finding 2** — `AutonomousTaskResult.to_dict()`: neuer `pending_package_approval`-Branch → `needs_package_install=True`, `needs_package_approval=True`, `event_type="approval_requested"`, `missing_packages=[...]`

**DoD-Check:**
- ✅ Non-allowlisted packages NEVER auto-installed
- ✅ Fail-closed: allowlist-fetch-error → empty set → pending_package_approval
- ✅ Rollback: `SKILL_PACKAGE_INSTALL_MODE=manual_only` → needs_package_install (kein Code-Revert)
- ✅ `needs_package_install` Compat-Field bleibt in pending_package_approval-Response
- ✅ Approval end-to-end verdrahtet: orchestrator speichert `approval_requested`, context_cleanup befüllt `pending_approvals`
- ✅ AutonomousTaskResult.to_dict() liefert vollen Signal-Pfad für UI/Caller
- ✅ 29 Tests (8 Finding-Fix-Tests) + 173 Regression, 0 failures

## Scope 3.1 — GPU vs RAM/CPU robust ✅ (2026-02-24)

**Ziel:** Embedding-Runtime-Policy technisch wirksam (auto|prefer_gpu|cpu_only), Fallbacks deterministisch + sichtbar, alle Embedding-Pfade identisch.

**Geänderte Dateien:**
- **`config.py`**: `get_embedding_runtime_policy()` — kanonischer Getter, liest `embedding_runtime_policy` (persisted) → `EMBEDDING_EXECUTION_MODE` (env) → "auto" (default)
- **`adapters/admin-api/settings_routes.py`**: `EmbeddingRuntimeUpdate` + `_EMBED_RUNTIME_DEFAULTS` um `embedding_runtime_policy` erweitert; `GET /api/settings/embeddings/runtime` zeigt aktive Policy + `active_policy` im Runtime-Snapshot; `POST` gibt `active_policy` zurück
- **`utils/embedding_resolver.py`**: `RoutingDecision` TypedDict (requested_policy, requested_target, effective_target, fallback_reason, hard_error, error_code + alle alten Felder backward-compat); `resolve_embedding_target()` um `availability: Optional[Dict[str, bool]]` + `optional_pin` erweitert; Decision matrix: cpu_only+cpu_down→503, prefer_gpu/auto+all_down→503, gpu_down→cpu_fallback
- **`utils/embedding_health.py`** *(neu)*: `check_embedding_availability(base, gpu_ep, cpu_ep, endpoint_mode)` — HTTP GET `/api/version` mit TTL-Cache (30s); single→beide Target = base; dual→je Endpoint unabhängig
- **`utils/embedding_metrics.py`** *(neu)*: `routing_fallback_total`, `routing_target_errors_total`, `embedding_latency_by_target`; `increment_fallback/error/record_latency/get_metrics/reset_metrics()`
- **`core/lifecycle/archive.py`**: `_get_embedding()` nutzt `get_embedding_runtime_policy()` statt `get_embedding_execution_mode()`; structured log `[Embedding] role=archive_embedding policy=... requested_target=... effective_target=... fallback=... reason=...`; hard_error → log_error + increment_error() + return None; fallback → increment_fallback(); latency recording
- **`sql-memory/embedding.py`**: `_inline_resolve_target()` um `availability` + alle RoutingDecision-Felder erweitert (backward-compat dict); `get_embedding()` mit structured log format identisch zu archive; hard_error → return None
- **`tests/unit/test_scope31_embedding_policy.py`** *(neu)*: 54 Tests (7 Klassen: Contract/DecisionShape/RouterMatrix/StructuredLogging/Metrics/RegressionCallSites/Integration)

**Verhaltensmatrix (verbindlich umgesetzt):**
- `cpu_only`: immer CPU; CPU unavailable → 503, kein GPU-Fallback
- `prefer_gpu`: GPU wenn ok; GPU down + CPU ok → CPU + warn-log + fallback_reason; all down → 503
- `auto`: bestes gesundes Ziel; GPU down → CPU + info-log; all down → 503
- `availability=None` (default): backward-compat optimistic (all available)

**DoD-Check:**
- ✅ embedding_runtime_policy Enum (auto|prefer_gpu|cpu_only) in typed settings, extra=forbid, 422 on invalid
- ✅ RoutingDecision mit requested_policy/requested_target/effective_target/fallback_reason/hard_error/error_code
- ✅ resolve_embedding_target(policy, availability, optional_pin) — deterministisch, alle Pfade identisch
- ✅ cpu_only darf niemals GPU nutzen (num_gpu=0 in single, dedicated CPU endpoint in dual)
- ✅ prefer_gpu GPU-down → CPU + warn-level log; auto GPU-down → CPU + info-level log
- ✅ all-down → hard_error=True, error_code=503; caller gibt None zurück
- ✅ structured logs: role=, policy=, requested_target=, effective_target=, fallback=, reason=
- ✅ metrics: routing_fallback_total, routing_target_errors_total, embedding_latency_by_target
- ✅ backward-compat: alter 'target'-Key bleibt, alle alten Callsites unverändert
- ✅ sql-memory inline-Mirror identisch zur utils-Implementierung
- ✅ 54 neue Tests, 0 failures; Full Gate: 995 passed, 4 skipped

## Was als nächstes kommt

*(Scope 3.1 abgeschlossen — nächste Phase: Scope 3.2 Embedding-Modellwechsel als Migration oder Scope 3.3 UI-Ehrlichkeit)*

**Bekannte Skips im Gate (akzeptiert, kein Fix nötig):**
- `test_phase15_budgeting.py` — 1 Skip (async fixture)
- `test_graph_hygiene_commit4.py` — 3 Skips (inspect kann MagicMock nicht durchleuchten), 2 Skips (commander_routes braucht FastAPI-Deps)

---

## Bekannte pre-existing Fehler (nicht unser Problem)

- `tests/unit/memory/` — 27 Errors wegen `config.DB_PATH` fehlt (Fixture veraltet)
- `tests/integration/test_light_cim.py` — standalone script, via `collect_ignore` ausgeschlossen
- `tests/reliability/test_*.py` — standalone scripts, via `collect_ignore_glob` ausgeschlossen
- `tests/sequential_thinking/`, `tests/mcp/test_installer.py` — fehlende Dependencies

---

## ACL-Info

- Das **gesamte `tests/`-Verzeichnis** ist ACL-geschützt → immer erst nach `/tmp` schreiben, testen, dann:
  ```bash
  echo "KriegimKopf1" | sudo -S cp /tmp/<datei>.py /DATA/AppData/MCP/Jarvis/Jarvis/tests/<pfad>/<datei>.py
  # Batch-Copy für ganze Verzeichnisse:
  echo "KriegimKopf1" | sudo -S bash -c 'cp /tmp/staging/* /DATA/AppData/MCP/Jarvis/Jarvis/tests/...'
  ```
- **Golden-Dateien** (`tests/golden/*.json`) ebenfalls ACL-geschützt:
  - Generieren nach `/tmp/golden/`, dann sudo-copy
  - Bei Tests außerhalb des Projekts: `AI_GOLDEN_DIR=/tmp/golden pytest ...`
- **Kein Push zu GitHub** (standing constraint)

---

## Kontext

- Projekt: **TRION / Jarvis** — KI-Assistent mit MCP, Container-Commander, Memory-System
- Danny ist der Entwickler; Claude hat TRION von der ersten Zeile an mitgebaut
- Codex macht regelmäßige Code-Reviews und schickt Findings zur Umsetzung
