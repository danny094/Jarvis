# Claude Code Implementation Handover (Phase 0-7)

## Ziel
Claude soll den Coding-Teil phasenweise umsetzen, mit klaren Invarianten, kleinen Commits und festen Gate-Checks.

## Nicht verhandelbare Invarianten
- Sync/Stream-Paritaet fuer denselben Kontexttyp.
- `build_effective_context()` ist der zentrale Entry-Point fuer Kontextaufbau.
- Keine Doppel-Injection von Tool-Ergebnissen (Single-Truth-Channel).
- Small-Model-Mode bleibt strikt dedupliziert und budgetiert.
- Fail-closed Defaults bei Sicherheits-/Datenintegritaets-Checks.
- Finaler Context-Cap wird nach allen Appends angewendet.

## Arbeitsmodus fuer Claude
1. Eine Phase nach der anderen.
2. Pro Phase: kleine, reviewbare Commits.
3. Nach jedem Commit die zugehoerigen Tests ausfuehren.
4. Bei roten Tests kein Phasenwechsel.
5. Keine Nebenpfade einbauen, wenn Builder/Hygiene-Pipeline existiert.

## Phasenplan (Implementierung + Abnahme)

### Phase 0
- Logging/Marker vereinheitlichen: `mode`, `context_sources`, `context_chars_final`, `retrieval_count`.
- Sync/Stream-Paritaet sicherstellen.
- Zieltests:
  - `python -m pytest -q tests/unit/test_orchestrator_context_pipeline.py --tb=short`
  - `python -m pytest -q tests/e2e/test_ai_pipeline_sync_stream.py --tb=short`

### Phase 1
- Zentraler Kontextpfad ueber `build_effective_context()`.
- Extra-Lookups (Control-Korrektur) ueber denselben Entry-Point.
- Sonderpfade/BYPASS ausserhalb des Builders entfernen.
- Zieltests:
  - `python -m pytest -q tests/unit/test_orchestrator_context_pipeline.py::TestBuildEffectiveContextPublicAPI --tb=short`

### Phase 1.5
- Hard-Cap im finalen Prompt-Assembly (nach allen Anhaengen).
- `tool_context` budgetieren/clippen.
- Failure-Compact in denselben Builder integrieren (kein Bypass).
- Zieltests:
  - `python -m pytest -q tests/unit/test_phase15_budgeting.py --tb=short`

### Phase 2
- Single-Truth-Channel fuer Output-De-Dup.
- Keine Doppel-Injection von Tool-Ergebnissen (Memory vs User Message).
- Small-Model-Mode strikt auf De-Dup-Verhalten.
- Zieltests:
  - `python -m pytest -q tests/unit/test_single_truth_channel.py --tb=short`
  - `python -m pytest -q tests/e2e/test_phase2_dedup.py --tb=short`

### Phase 3
- TypedStateV1: Facts/Entities + `source_event_ids`.
- Pipeline: `normalize -> dedupe(window) -> correlate -> select_top(budget) -> render NOW/RULES/NEXT`.
- Fail-closed auf Minimal-NOW bei Fehlern.
- Observability-Meta fuer TypedState.
- Zieltests:
  - `python -m pytest -q tests/unit/test_typedstate_csv_loader.py --tb=short`
  - `python -m pytest -q tests/e2e/test_phase3_typedstate.py --tb=short`

### Phase 4
- Restart-Recovery fuer Container-Active-State (Docker scan -> rebuild).
- TTL-Rearm via Labels/Timer-Rekonstruktion.
- Recovery-Tests fuer ACTIVE_CONTAINER + TTL.
- Zieltests:
  - `python -m pytest -q tests/unit/test_container_restart_recovery.py --tb=short`
  - `python -m pytest -q tests/e2e/test_phase4_recovery.py --tb=short`

### Phase 5
- Zentrale Graph-Hygiene-Pipeline (`core/graph_hygiene.py`).
- Router + Context auf dieselbe Hygiene-Pipeline.
- Dedupe pro `blueprint_id` + latest-revision selection.
- SQLite active-set Cross-Check fail-closed gegen stale/soft-deleted Nodes.
- Delete-Konsistenz via Tombstone + Reconcile-Tool.
- Zieltests:
  - `python -m pytest -q tests/unit/test_graph_hygiene.py tests/unit/test_graph_hygiene_commit4.py --tb=short`
  - `python -m pytest -q tests/e2e/test_phase5_graph_hygiene.py --tb=short`

### Phase 6
- Signature Verify: Stub -> echte Pruefung (`off | opt_in | strict`).
- Runtime-Wiring im Engine-Deploy-Pfad inkl. Block-Handling/Audit-Event.
- Markdown/XSS-Sanitizing zentral fuer Workspace + Protocol.
- REST Deploy Parity: `session_id`/`conversation_id` durchreichen + rueckgeben.
- Zieltests:
  - `python -m pytest -q tests/unit/test_phase6_security.py --tb=short`

### Phase 7
- Test-Harness fuer sync/stream + mock/live Provider.
- Dataset-Schema + Validator + Cases.
- Golden-Regression fuer Small-Model-Mode.
- Phasen-E2E (2-6).
- Gate-Disziplin (`quick/full/live`) inkl. Doku.
- Zieltests:
  - `./scripts/test_gate.sh`
  - `./scripts/test_gate.sh full`
  - `AI_TEST_LIVE=1 ./scripts/test_gate.sh live` (nur mit Live-Backend)

## Empfohlene Datei-Hotspots
- Kontext/Orchestrierung: `core/orchestrator.py`, `core/context_manager.py`, `core/layers/output.py`
- TypedState/Context-Cleanup: `core/context_cleanup.py`, `core/typedstate_csv_loader.py`
- Graph-Hygiene: `core/graph_hygiene.py`, `core/blueprint_router.py`, `container_commander/blueprint_store.py`, `tools/reconcile_graph_index.py`
- Security/Parity: `container_commander/trust.py`, `config.py`, `adapters/Jarvis/static/js/sanitize.js`, `adapters/admin-api/protocol_routes.py`, `adapters/admin-api/commander_routes.py`
- Gates/Harness/Datasets: `tests/harness/*`, `tests/datasets/*`, `tests/e2e/*`, `scripts/test_gate.sh`

## Finaler Abnahme-Block (muss gruen sein)
```bash
./scripts/test_gate.sh
./scripts/test_gate.sh full
```

## Copy/Paste Prompt fuer Claude
```text
Arbeite den Phasenplan 0 bis 7 in dieser Reihenfolge ab. Nutze kleine Commits pro Phase, halte die Invarianten ein (Sync/Stream-Paritaet, build_effective_context als Single Entry Point, Single-Truth-Channel, fail-closed Defaults, final cap nach allen Appends). Fuehre nach jeder Phase die genannten Zieltests aus und stoppe bei Fehlern bis alles gruen ist. Keine Bypass-Pfade einfuehren, wenn zentrale Builder/Pipelines existieren. Zum Abschluss: quick + full gate gruen melden und pro Phase kurz nennen: geaenderte Dateien, bestandene Tests, offene Risiken.
```
