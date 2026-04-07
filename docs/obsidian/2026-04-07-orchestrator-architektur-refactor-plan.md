# Orchestrator-Architektur-Refactor-Plan

Erstellt am: 2026-04-07
Status: **Geplant**

## Ausgangslage

`core/orchestrator.py` ist inzwischen ein echter Wartungsblocker:

- zu viele Verantwortlichkeiten in einer Datei
- hoher Review- und Testaufwand pro Aenderung
- schlechte Parallelisierbarkeit fuer mehrere Arbeitsstraenge
- hohe Seiteneffektgefahr selbst bei kleinen Anpassungen

Nach dem aktuellen Produktisierungs- und Härtungsstand ist jetzt der richtige
Zeitpunkt fuer einen Architekturpfad:

- Live-Fixes und Git-Safety sind auf `main`
- die grossen Runtime-/Container-/Contract-Pfade sind nun nicht mehr nur lokal,
  sondern im Hauptrepo angekommen
- weitere Produktarbeit sollte nicht dauerhaft in denselben Monolithen
  hineingeschichtet werden

## Zielbild

Kein grosser Rewrite, sondern kontrollierte Extraktion in fachlich trennbare
Module.

Wichtige Leitplanken:

1. keine Verhaltensaenderung als Primärziel
2. kleine, testbare Schnitte statt Big-Bang-Refactor
3. erst Entscheidungslogik, dann stateful/runtime-nahe Pfade
4. jeder Schnitt bekommt vorher oder parallel Pinning-Regressionen

## Warum kein Big-Bang-Rewrite

Ein kompletter Neubau des Orchestrators wuerde aktuell mehr Risiko als Nutzen
bringen:

- zu viele lebende Produktpfade haengen daran
- Streaming-, Sync-, Control-, Grounding- und Containerpfade greifen ineinander
- die bestehenden Regressionen sind inzwischen wertvoll genug, dass man sie
  lieber zur Extraktion als zur Neuschreibung nutzt

Deshalb gilt:

- erst entflechten
- dann weiter verkleinern
- erst spaeter groessere Signatur- oder Ownership-Aenderungen

## Kandidaten fuer die Zielstruktur

Sinnvolle Extraktionsmodule:

- `orchestrator_domain_routing.py`
- `orchestrator_container_policy.py`
- `orchestrator_grounding.py`
- `orchestrator_workspace_events.py`
- `orchestrator_skill_catalog.py`
- `orchestrator_response_repair.py`

Diese Namen sind noch Arbeitstitel. Wichtig ist die fachliche Trennung, nicht
der exakte Dateiname.

## Empfohlene Extraktionsreihenfolge

### Phase 1: Fast-pure Entscheidungslogik

Zuerst rausziehen:

- Domain-/Policy-Gates
- Tool-Auswahl-Normalisierung
- Container-Query-/Routing-/Binding-/Home-Tool-Shaping
- Grounding-/Repair-Entscheidungslogik

Warum zuerst:

- deutlich besser testbar
- weniger versteckter Runtime-Zustand
- hoher Wartungsgewinn bei vergleichsweise kontrollierbarem Risiko

### Phase 2: Semantische Kontext- und Kataloglogik

Danach:

- Skill-Katalog-Pfade
- Addon-/Query-Class-bezogene Antwortlogik
- Antwortreparatur und sichtbarer Contract-Fallback

### Phase 3: Stateful/runtime-nahe Pfade

Spaeter:

- Conversation-/Binding-State
- Lifecycle-Hooks
- Streaming-/Sync-Verzweigung
- Tool-Ausfuehrungskoordination
- Workspace-Event-Persistenz

Diese Teile sind riskanter und sollten erst nach den reinen
Entscheidungsmodulen folgen.

## Bester erster Schnitt

Der erste Refactor-Schnitt sollte **nicht** bei `process_request(...)` beginnen.

Besserer Startpunkt:

- Container-/Domain-Policy im Orchestrator

Konkret:

- `_resolve_execution_suggested_tools`
- Container query policy override
- Domain route enforcement
- Home / request / binding tool shaping

Warum genau dieser Block:

- fachlich inzwischen deutlich klarer als noch frueher
- bereits gut mit Regressionen abgesichert
- relativ sauber gegen die restliche Antwortgenerierung abgrenzbar

## Pinning-Regressionen vor jedem Schnitt

Vor jedem Extraktionsschritt muessen die relevanten Verhaltenspfade mit
Pinning-Tests abgesichert bleiben.

Pflichtblöcke:

- `container_request`
- `TRION Home`
- `container_state_binding`
- `container_inventory`
- skill catalog
- workspace events
- output repair
- control authority

## Explizite Nicht-Ziele fuer den ersten Schritt

Nicht gleichzeitig mit dem Refactor mischen:

- neue Produktfeatures
- UI-Umbauten ohne Architekturbezug
- neue Toolfamilien
- neue Persistenzmodelle ausserhalb klar betroffener Extraktionspfade
- grossflaechige API-Signaturwechsel

## Praktischer naechster Schritt

Vor dem ersten Code-Refactor ein kurzer Architektur-Audit:

1. aktuelle Funktionscluster in `core/orchestrator.py` benennen
2. pure vs. stateful Bereiche markieren
3. ersten sicheren Extraktionsschnitt festlegen
4. benoetigte Pinning-Tests benennen

Erst danach der eigentliche Codeschnitt.
