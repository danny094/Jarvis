# PHASE 4 / PRIO-1 Handover (2026-02-18)

## Status
- In Implementierung.
- Nächster Schritt: Claude-Umsetzung prüfen (Sync/Stream Parität + Context Trace + Single Entry-Point).

## Fokus für morgen
1. Prüfen, dass **ein zentraler Context-Assembler** in `core/orchestrator.py` verwendet wird.
2. Prüfen, dass alle drei Pfade über denselben Helper laufen:
   - Sync Main Context
   - Stream Main Context
   - Sync Extra `get_context` Pfad (Control-Korrektur)
3. Prüfen, dass `small_model_mode` überall konsistent durchgereicht wird.
4. Prüfen, dass `context_trace` vorhanden ist mit:
   - `small_model_mode`
   - `context_sources`
   - `context_chars`
   - `context_blocks`
   - `retrieval_count`
   - `flags.skills_prefetch_used`
   - `flags.detection_rules_used`
   - `flags.output_reinjection_risk`
5. Prüfen, dass CTX-One-Liner Logs in Sync + Stream kommen.
6. Optional: Dry-Run Flag `CONTEXT_TRACE_DRYRUN` prüfen (default false).

## Relevante Stellen (für Review)
- `core/orchestrator.py` (Context Build Sync/Stream + extra lookup)
- `core/layers/thinking.py` (Detection Rules Injection)
- `core/layers/output.py` (Output Reinjection Risiko)
- `config.py` (Trace/Dryrun Flags)

## Ziel dieses PRIO-1 Schritts
- Minimal-invasive Zentralisierung + Observability.
- Keine breite Architekturänderung.
- Vorbereitung für TypedStateV1 in späterem Schritt.
