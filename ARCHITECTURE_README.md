# TRION Architecture README (for Claude Code)

Dieses Dokument ist ein praktischer Architektur-Handover, damit du nahtlos mit Claude Code weiterarbeiten kannst.
Ziel: schneller Einstieg in Gesamtfluss, zentrale Module, Invarianten und typische Änderungsorte.

## 1. Architektur auf einen Blick

TRION ist ein lokal-first Multi-Service-System mit klar getrennten Schichten:

1. `Thinking` analysiert User-Input und erzeugt einen Plan (`thinking_plan`).
2. `Control` ist die Policy-Authority und trifft die Sicherheits-/Freigabeentscheidung (`control_decision`).
3. `Executor` führt nur Side-Effects aus (`execution_result`) und darf keine Policy neu entscheiden.
4. `Output` formuliert die Antwort auf Basis von Plan, Evidenz und Ausführungsresultaten.

Kernprinzip: **Single Control Authority**. Entscheidungsmacht bleibt bei Control; nachgelagerte Layer lesen Entscheidung nur.

## 2. Laufende Services (wichtig für Debugging)

Hauptports (laut aktuellem Repo-Setup):

- `jarvis-webui`: `8400`
- `jarvis-admin-api`: `8200`
- `tool-executor`: `8000`
- `skill-server`: `8088`
- `mcp-sql-memory`: `8082`
- `trion-runtime`: `8401`
- `validator-service`: `8300`

Wichtige Einstiegspunkte:

- UI/API Proxy: `app.py`
- Admin API: `adapters/admin-api/main.py`
- Core Bridge: `core/bridge.py`
- Orchestrator: `core/orchestrator.py`
- MCP Hub: `mcp/hub.py`
- Skill Server: `mcp-servers/skill-server/server.py`
- Tool Executor: `tool_executor/api.py`

## 3. Request Flow (praktisch)

### 3.1 Chat/Sync Pfad

1. Request kommt über Adapter/API (`/api/chat` in Admin API).
2. `core.bridge.CoreBridge` delegiert zu `PipelineOrchestrator`.
3. `ThinkingLayer.analyze(...)` erzeugt `thinking_plan`.
4. `ControlLayer.verify(...)` erzeugt Verifikation.
5. Verifikation wird in `control_decision` überführt (`core/control_contract.py`).
6. Toolausführung produziert `_execution_result`.
7. `OutputLayer.generate(...)` erstellt die finale Antwort.

### 3.2 Stream Pfad

- `PipelineOrchestrator.process_stream_with_events(...)` nutzt denselben Kernfluss, aber mit Event-Emission + Chunking.

## 4. Policy-Modell (entscheidend für Stabilität)

### 4.1 Typisierte Vertragsobjekte

`core/control_contract.py` trennt strikt:

- `ControlDecision` (immutable, policy)
- `ExecutionResult` (mutable, runtime)

Regel:

- Guard/Executor/Output dürfen `control_decision` lesen, aber nicht überschreiben.
- Runtime-Fehler werden als `done_reason` (z. B. `tech_fail`, `unavailable`) im `execution_result` geführt.

### 4.2 Warum das wichtig ist

Das verhindert Drift durch doppelte Policy-Interpretation in nachgelagerten Layern.

## 5. Module-Übersicht nach Verzeichnis

### 5.1 `core/`

- `orchestrator.py`: zentrale Pipeline-Orchestrierung
- `bridge.py`: Backward-compat Einstieg (`get_bridge()`)
- `layers/thinking.py`: Plan-Extraktion + Toolvorschläge
- `layers/control.py`: Policy/Safety-Freigabe
- `layers/output.py`: Antwortgenerierung
- `context_manager.py`: Memory + Tool/Systemkontext Retrieval
- `control_contract.py`: Typed policy/runtime contracts
- `orchestrator_*_utils.py`: ausgelagerte Orchestrator-Teilfunktionen
- `tool_execution_policy.py`, `grounding_policy.py`: deterministische Leitplanken
- `autonomy/`: Cron-/Autonomie-Laufzeit

### 5.2 `mcp/`

- `hub.py`: Transport-/Tool-Aggregation über MCPs
- `endpoint.py`: MCP HTTP Endpoints (`/mcp`, `/mcp/tools`, ...)
- `transports/`: HTTP/SSE/STDIO Transports

### 5.3 `sql-memory/`

- `memory_mcp/tools.py`: Memory-Tools (save/search/facts/workspace/...)
- Graph + Vektorstore + DB-Layer für persistenten Kontext

### 5.4 `container_commander/`

- `engine.py`: Docker Lifecycle + Exec + Quota + TTL
- `blueprint_store.py`: Blueprint-Layer + Graph-Sync
- `mcp_tools.py` / `mcp_bridge.py`: Commander Tools im Hub

### 5.5 Skills

- `mcp-servers/skill-server/`: Skill Discovery/Creation/Policy-Vorstufe
- `tool_executor/`: Layer-4 Side-Effect Runtime für Skill Create/Run

Kritisch:

- In `tool_executor/api.py` gilt `SKILL_CONTROL_AUTHORITY=skill_server` als Default.
- Executor validiert Contract, aber trifft nicht nochmal die Haupt-Policy.

### 5.6 Adapter/UI

- `adapters/admin-api/`: zentrale Management- und Chat-API
- `adapters/Jarvis/`: Frontend-Apps (Chat, Tools, Settings, Session, Cron)
- `adapters/lobechat/`, `adapters/openwebui/`: weitere Integrationen

## 6. Architektur-Prioritäten (aktueller Projektfokus)

Diese Leitlinien waren zuletzt zentral und sollten beibehalten werden:

1. So wenig hardcodete Prompts wie möglich.
2. Autonomie erhalten (nicht durch Prompt-Bloat ersticken).
3. Rules + Embeddings als Signale nutzen; Entscheidung bleibt bei Control.
4. Keine versteckten Policy-Pfade in Executor/Output.

## 7. Wichtige Invarianten für Änderungen

1. **Control bleibt Authority**: kein zweiter Policy-Block in Runtime-Layern.
2. **`control_decision` ist read-only downstream**.
3. **`execution_result` enthält keine Policy-Entscheidungen**.
4. **Tool-Gates deterministisch halten** (Budget, Suppress, Host-/Runtime-Regeln).
5. **Fast-Lane Tools bleiben direkt verfügbar** (Hub registriert sie früh).

## 8. Typische Änderungsorte nach Aufgabe

- Prompt-/Plan-Qualität: `core/layers/thinking.py`, `core/orchestrator_prompt_utils.py`
- Policy-/Freigabelogik: `core/layers/control.py`, `core/control_policy_utils.py`, `core/control_contract.py`
- Tool-Ausführung/Argumente: `core/orchestrator_tool_*`, `core/orchestrator_stream_flow_utils.py`, `core/orchestrator_sync_flow_utils.py`
- Skill-Autonomie: `mcp-servers/skill-server/mini_control_core.py`, `tool_executor/mini_control_core.py`, `tool_executor/api.py`
- Containerpfad: `container_commander/*`
- Memory/Grounding: `core/context_manager.py`, `sql-memory/*`, `core/grounding_*`

## 9. Teststrategie im Repo

- Großteil läuft als Unit/Contract-Tests.
- Einige Suiten sind bewusst als Live-Opt-in gegated (externe Dienste nötig).

Aktuelle relevante Gates:

- `RUN_AUTONOMOUS_SKILL_INTEGRATION=1`
- `RUN_PIPELINE_LIVE_TESTS=1`
- `RUN_COMPREHENSIVE_INTEGRATION=1`
- `RUN_PERSONA_REST_API_TESTS=1`
- (bestehend) `RUN_REAL_MEMORY_INTEGRATION=1`, `RUN_CIM_LIVE_TESTS=1`

Standard-validierung:

```bash
pytest -q -x
```

## 10. Konkrete Start-Reihenfolge für Claude Code

1. `README.md` lesen (Runtime/Ports/Operations).
2. Dieses Dokument lesen.
3. Für Pipeline-Arbeiten: `core/orchestrator.py` + `core/orchestrator_*_utils.py` + `core/control_contract.py`.
4. Für Skill-Arbeiten: `mcp-servers/skill-server/server.py`, `mini_control_core.py`, `tool_executor/api.py`.
5. Für Container-Arbeiten: `container_commander/engine.py` + `blueprint_store.py`.
6. Danach immer mit kleinem zielgerichteten Testset starten, erst dann Full Suite.

## 11. Debug-Checkliste (kurz)

- Drift/Policy: prüfen, ob irgendwo `control_decision` neu interpretiert wird.
- Tool-Fails: `done_reason` + `tool_statuses` prüfen statt impliziter Fehlertexte.
- Kontextprobleme: `build_effective_context` Trace (`retrieval_count`, `context_sources`).
- Skill Install: zuerst `control_decision`-Payload, dann Executor-Endpoint/Fallbacks.
- Test-Contamination: auf globale `sys.modules`/`sys.path` Seiteneffekte achten.

## 12. Weiterführende interne Dokus

- `docs/session-handoff-latest.md`
- `docs/contracts/trion-chat-event-contract.md`
- `docs/digest_rollout_runbook.md`
- `docs/trion-priority-implementation-plan-2026-03-03.md`

---

Wenn Claude Code dieses Dokument nutzt, sollte die Orientierung für neue Änderungen in wenigen Minuten möglich sein, ohne alte Session-Kontexte zu kennen.
