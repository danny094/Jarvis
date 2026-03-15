# TRION Pre-Cron Readiness Checklist (2026-03-09)

## Ziel
Vor Einführung von Cronjobs sicherstellen, dass autonome Objectives robust, eindeutig auswertbar und betriebssicher laufen.

## Statusübersicht
- [ ] R1: Autonomy-Planning Tools Runtime-ready
- [ ] R2: Eindeutige Success/Failure-Semantik für `/api/autonomous`
- [ ] R3: Autonomy Job Queue + Cancel/Retry (wie Deep-Jobs)
- [ ] R4: Autonomy Policy Feinschliff (Reason-Codes, fast-vs-deep)

## R1: Autonomy-Planning Tools Runtime-ready
Problem:
- `GET /api/runtime/autonomy-status` meldet `planning_tools.all_required_available=false`.
- `sequential_thinking` ist aktuell nicht verfügbar.

Abnahmekriterien:
1. `planning_tools.available.sequential_thinking == true`
2. `planning_tools.all_required_available == true`
3. Health-Check stabil unter Last (parallel Chat + 1 autonomer Lauf)

Validierung:
- `curl /api/runtime/autonomy-status`
- gezielter Contract-Test für Tool-Availability

---

## R2: Eindeutige Success/Failure-Semantik für `/api/autonomous`
Problem:
- Fälle beobachtet, in denen API `success=true` liefert, obwohl ein `planning_error` (z. B. `max_loops_reached`) auftrat und `final_state` nicht `completed` war.

Abnahmekriterien:
1. `success=true` nur bei final_state `completed`
2. Bei Guard-Abbruch (`max_loops_reached`, `too_many_failures`, `loop_detected`) immer `success=false`
3. Fehlercode/Grund maschinenlesbar im Response (z. B. `error_code`)

Validierung:
- Unit-Test für Master-Orchestrator Result-Semantik
- API-Test für `/api/autonomous` mit `max_loops=1`

---

## R3: Autonomy Job Queue + Cancel/Retry
Problem:
- Deep-Jobs haben Queue/Cancel/Stats, Autonomy-Objectives laufen aktuell direkt.
- Für Cronjobs fehlt damit robuste Entkopplung (Overlap-Schutz, Retry, Observability).

Abnahmekriterien:
1. Neue Job-Lifecycle für Autonomy: `queued`, `running`, `succeeded`, `failed`, `cancelled`
2. Endpunkte analog zu Deep-Jobs:
   - submit
   - status by id
   - cancel
   - runtime stats
3. Retry-Policy (mind. `attempt`, `max_attempts`, `next_retry_at`)
4. Doppelte Cron-Trigger erzeugen keine unkontrollierten Parallel-Läufe

Validierung:
- Contract-Tests für alle Endpunkte
- E2E-Test: submit -> cancel -> terminal status
- E2E-Test: fail -> retry -> status progression

---

## R4: Autonomy Policy Feinschliff
Problem:
- In der laufenden Doku ist Policy-Feinschliff noch offen (Reason-Codes, deep-vs-fast-path).

Abnahmekriterien:
1. Jeder Abbruchpfad hat stabilen reason-code (`no_tools`, `max_loops_reached`, ...)
2. Policy-Entscheidung für fast/deep nachvollziehbar geloggt
3. Workspace-Events tragen kompakten maschinenlesbaren Decision-Context

Validierung:
- Unit-Tests auf reason-codes
- Workspace-Event-Contract-Tests für neue Felder

---

## Empfohlene Reihenfolge
1. R2 (Response-Semantik, kleinster Hebel mit hoher Wirkung)
2. R1 (Runtime-Tool-Readiness)
3. R3 (Queue/Cancel/Retry als Cron-Basis)
4. R4 (Policy-Feinschliff final)

## Go/No-Go vor Cronjobs
Go nur wenn:
1. R1-R4 alle erledigt
2. Full Bottleneck Gate weiterhin grün
3. Mindestens ein Autonomy-E2E mit Queue + Cancel + Retry grün
