# TRION Planungsstrategie: Model-Routing, Embedding Runtime, Multi-GPU

**Stand:** 2026-02-23  
**Owner:** Jarvis Core + Admin API + WebUI  
**Zweck:** Verbindliche Umsetzungs-Roadmap, damit Architektur- und Scope-Entscheidungen in einer Woche nachvollziehbar sind.

---

## 1) Zielbild

Der User kann in der WebUI pro Rolle steuern:

- `Thinking` Modell
- `Control` Modell
- `Output` Modell
- `Tool Selector` Modell
- `Embedding` Modell
- `Embedding Compute Target`: `Auto | GPU bevorzugt | CPU (RAM, kein GPU-Offload)`
- Optional später: `konkrete GPU-Instanz` bei Multi-GPU (z. B. `GPU0`, `GPU1`, `GPU2`)

Gleichzeitig gilt:

- Keine Schein-Settings mehr.
- Runtime-Änderungen wirken ohne Neustart (wo technisch möglich).
- Alle Embedding-Pfade nutzen dieselbe effektive Konfiguration.
- Keine stillen Datenmischungen bei Embedding-Modellwechsel.

---

## 2) Bereits erledigt (Status-Checkpoint)

### 2.1 Single Source of Truth (Model Settings)
- Neue typed Endpoints für Model-Settings sind eingeführt (`/api/settings/models`, `/api/settings/models/effective`).
- UI-Defaults sind nicht mehr hardcoded preselected.
- Effective-Precedence ist definiert: `settings override > env > default`.

### 2.2 Live-Wirkung statt Import-Freeze
- Thinking/Control/Output lösen Modelle zur Laufzeit statt nur über Import-Konstanten.
- Whitespace-Overrides sind bereinigt.

### 2.3 Embedding in mehreren Pfaden konsistent
- Embedding-Resolver ist in den zentralen Aufrufpfaden verdrahtet.
- `sql-memory` nutzt Resolver + API-Fallback + TTL-Cache.
- Compose hat `SETTINGS_API_URL` für `mcp-sql-memory`.

---

## 3) Offener Kernscope (nächster Block)

### 3.1 GPU vs RAM/CPU klar und robust
- Runtime-Policy für Embeddings definieren: `auto`, `prefer_gpu`, `cpu_only`.
- Explizite Fallback-Regeln implementieren (z. B. GPU nicht verfügbar -> CPU, mit Log/Event).

### 3.2 Embedding-Modellwechsel als Migration behandeln
- Alte und neue Vektoren nicht still mischen.
- Versionierung pro Vektor (`embedding_model`, optional `embedding_dim`, `version_id`).
- Re-Embedding/Backfill-Mechanismus einführen.

### 3.3 UI wieder ehrlich freigeben
- Models/Embedding-Controls nur dort anzeigen, wo Runtime tatsächlich wired ist.
- Sonst in `Advanced` als klar begrenzter Runtime-Block.

---

## 4) Architekturentscheidung (Empfohlen)

## 4.1 Entscheidung
Einführen eines **Ollama Endpoint Managers** mit kontrolliertem Lifecycle:

- Instanzen: `cpu`, `gpu0`, `gpu1`, `gpu2`, ...
- Jede Instanz hat festen Endpoint (intern) und feste Device-Bindung.
- Rollen-Routing mappt auf Instanz-Profile.

Warum:

- Pro-Request-Flags (`num_gpu=0`) sind je nach Ollama-Version/Endpoint nicht gleich robust.
- Multi-GPU-Zuordnung wird deterministisch.
- Betrieb/Debugging ist klarer als implizite Magic pro Request.

### 4.2 Sicherheitsgrenzen (hart)
- Nur vordefinierte Container-Templates.
- Kein frei wählbarer Docker-Command aus der UI.
- Whitelist für Image, Env, Volumes, Network.
- Keine extern exponierten Zufallsports.

---

## 5) Zielkomponenten

1. **Settings Contract**
- `embedding_runtime_policy`: `auto | prefer_gpu | cpu_only`
- `embedding_target_instance`: `auto | cpu | gpu0 | gpu1 | ...` (optional Phase 2)
- `layer_routing`: Map für `thinking/control/output/tool_selector/embedding`

2. **Endpoint Registry**
- Hält laufende Ollama-Instanzen + Health + Capability (GPU/CPU, VRAM, Last seen).

3. **Instance Manager**
- Start/Stop/Status nur über Templates.
- Optional TTL Auto-Stop für ungenutzte Instanzen.

4. **Runtime Router**
- Wählt Endpoint pro Rolle.
- Wendet Fallback-Policy an.
- Liefert klare Logs: `requested_target`, `effective_target`, `fallback_reason`.

5. **Embedding Versioning Layer**
- Speichert Vektor-Metadaten.
- Blockiert Mischzustände oder markiert sie explizit.

---

## 6) API-Plan (typed, minimal)

### 6.1 Runtime/Compute
- `GET /api/runtime/compute/instances`
- `POST /api/runtime/compute/instances/{id}/start`
- `POST /api/runtime/compute/instances/{id}/stop`
- `GET /api/runtime/compute/routing`
- `POST /api/runtime/compute/routing`

### 6.2 Settings
- Erweiterung bestehender Model-Settings um `embedding_runtime_policy` und (optional) `embedding_target_instance`.

### 6.3 Contracts
- Strikte Validierung (`extra=forbid`).
- Einheitliche Fehlercodes (`422` Validation, `409` Conflict, `503` Dependency unavailable).

---

## 7) UI-Plan

### 7.1 Neuer Bereich
`Advanced > Embeddings Runtime`:

- Policy: `Auto | GPU bevorzugt | CPU`
- Optional Instanz-Pinning: `Auto / CPU / GPU0 / GPU1 / ...`
- Health-Karte je Instanz (Running/Stopped/Unavailable)

### 7.2 Später (wenn stabil)
`Settings > Models` wieder freischalten:

- Pro Layer Modellwahl
- Pro Layer optionales Compute-Target (nur wenn vollständig supported)

### 7.3 UX-Regeln
- Ehrliche Labels (kein verstecktes Verhalten).
- Aktiver Effective-Wert + Source anzeigen.
- Bei Fallback sichtbarer Hinweis (nicht still).

---

## 8) Daten-/Migrationsstrategie für Embeddings

1. Speicher-Metadaten erweitern:
- `embedding_model`
- `embedding_dim` (wenn verfügbar)
- `embedding_version` (z. B. Hash aus model+policy)
- `created_at`

2. Query-Regel:
- Standard: nur aktive `embedding_version`.
- Altversion optional für Backfill-Phase, aber klar markiert.

3. Backfill-Job:
- Batchweise Re-Embedding
- Fortschritt/Fehlerstatus
- Abbruch-/Resume-fähig

4. Cutover:
- Erst wenn Coverage-Schwelle erreicht (z. B. 95%).
- Danach alte Version archivieren oder löschen.

---

## 9) Fallback- und Failure-Policy

Mindestregeln:

- `cpu_only`: niemals GPU-Offload.
- `prefer_gpu`: wenn Ziel-GPU down/unavailable, auf CPU fallback mit Warn-Event.
- `auto`: wählt bestes verfügbares Ziel nach Health/Priority.
- Harte Fehler nur bei explizitem Pinning ohne erlaubten Fallback.

Observability:

- Structured Logs pro Request:
  - `role`
  - `requested_target`
  - `effective_target`
  - `policy`
  - `fallback`
- Runtime-Metriken:
  - requests per target
  - fallback count
  - target errors
  - average latency by target

---

## 10) Phasenplan mit Aufwand

## Phase A (2-4 Tage): Contract + Router + Policy
- Settings-Felder ergänzen (typed).
- Runtime-Router für Embeddings mit Policy/Fallback.
- Unit-Tests + API-Tests.
- Ergebnis: CPU/GPU-Policy technisch wirksam, auch ohne dynamische Container.

## Phase B (3-6 Tage): Endpoint Manager (Start/Stop, Status)
- Registry + Manager + sichere Templates.
- Runtime-Endpoints für Instance lifecycle.
- UI-Statuspanel.
- Ergebnis: Instanzen kontrolliert per UI verwaltbar.

## Phase C (3-5 Tage): Multi-GPU Pinning pro Rolle
- Routing pro Layer auf Instanz-ID.
- Health-Checks + Failover-Regeln.
- Ergebnis: z. B. Control -> GPU2, Output -> GPU1, Embedding -> CPU.

## Phase D (4-8 Tage): Embedding-Versionierung + Backfill
- Schema/Metadaten + Query-Filter.
- Re-Embedding-Job + Fortschritt.
- Ergebnis: Modellwechsel ohne stille Drift.

**Grobe Gesamtgröße:** mittel bis groß (ca. 2-4 Wochen inkl. Stabilisierung, abhängig von UI-Tiefe und Migrationsvolumen).

---

## 11) Teststrategie (Definition of Done)

1. Contract-Tests
- Unknown Fields -> `422`
- Invalid enum -> `422`
- Effective config korrekt nach Precedence

2. Router-Tests
- Jede Policy + Fallback-Pfad
- Pinned target unavailable
- CPU-only garantiert ohne GPU-Nutzung

3. Manager-Tests
- Nur erlaubte Templates startbar
- Start/Stop idempotent
- Health-Status korrekt

4. Integrations-/E2E
- UI speichert und zeigt effektive Werte korrekt
- Routing wirkt im echten Requestpfad
- Multi-GPU Zuweisung bleibt stabil über Neustarts

5. Migration-Tests
- Kein Mischen alter/neuer Embeddings ohne Marker
- Backfill resume/cancel
- Query nur aktive Version

---

## 12) Risiken und Gegenmaßnahmen

1. **Container-Sprawl**
- Gegenmaßnahme: TTL-Auto-Stop + max Instanzen + Quotas.

2. **Sicherheitsrisiko durch Docker-Steuerung**
- Gegenmaßnahme: strict template whitelist, kein arbitrary command path.

3. **Race Conditions bei Start/Stop**
- Gegenmaßnahme: per-instance lock + idempotente Endpoints.

4. **Uneinheitliche Modelllisten je Instanz**
- Gegenmaßnahme: shared model volume + warmup/health checks.

5. **Leistungs-/Latenzdrift**
- Gegenmaßnahme: per-target telemetry + adaptive routing optional später.

---

## 13) Klare Entscheidungen für nächste Woche

Bis zum nächsten Review sollten folgende Punkte final entschieden sein:

1. `Option A` bestätigen: Endpoint Manager als Standardarchitektur.
2. Fallback-Matrix finalisieren (`auto`, `prefer_gpu`, `cpu_only`, pinned).
3. Mindest-UI für Phase A/B festlegen (Advanced-Panel vs vollständige Models-Seite).
4. Embedding-Migrationspolicy (block/allow mixed during backfill) verbindlich definieren.
5. Rollout-Reihenfolge pro Umgebung (dev -> staging -> prod) terminieren.

---

## 14) Kurzprotokoll (Decision Log)

- **2026-02-23:** Planung konsolidiert.  
- **2026-02-23:** Präferenz Richtung Endpoint Manager dokumentiert.  
- **2026-02-23:** Embedding-Versionierung als Pflicht bei Modellwechsel festgehalten.  
- **2026-02-23:** UI-Ehrlichkeit als Freigabekriterium definiert (kein Schein-Feature).

