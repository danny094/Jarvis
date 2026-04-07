# Gaming Station + Sunshine Handoff

Stand dieser Notiz: 2026-03-28
Status: Gestoppt und archiviert am 2026-04-01. Historische Mischstand-Notiz, nicht mehr kanonisch.

Hinweis: Der zugehoerige `gaming-station`-/Gaming-Container-Pfad ist nicht mehr aktiv.

## Zweck

Diese Notiz war ein operatives Handoff waehrend mehrerer Architekturwechsel.
Sie enthielt gleichzeitig:

- alten `primary`-/Container-Sunshine-Stand
- spaeteren Host-Bridge-Stand
- Marketplace-/Shadow-/GitHub-Installtests
- fruehe Storage- und Runtime-Zwischenbefunde

Genau deshalb ist sie heute als operative Quelle ungeeignet.

## Heute gueltige Lesereihenfolge

Fuer `gaming-station` bitte nur noch in dieser Reihenfolge lesen:

1. `2026-03-24-gaming-station-container-doc.md`
   Aktueller operativer Ist-Stand.
2. `2026-03-26-gaming-station-diagnostic-und-fixes.md`
   Historische Diagnosekette mit belegten Root Causes und Fixes.
3. `2026-03-28-gaming-station-host-runtime-discovery-implementationsplan.md`
   Scope-Wechsel weg von Host-Mutation hin zu read-only Host-Runtime-Discovery.

## Historisch wichtige Entscheidungen aus dieser alten Handoff-Phase

- `gaming-station` ist nicht mehr auf dem alten `primary`-/Container-Sunshine-Pfad das Zielbild.
- `gaming-station` ist heute Host-Bridge / `MODE=secondary`.
- Sunshine bleibt auf dem Host.
- `stop` behaelt `gaming-station`, `uninstall` entfernt den gestoppten Container.
- Die fruehere Mod-/Steam-Library-Verwirrung wurde auf `data/steam-home` als aktive Quelle reduziert.
- Der spaetere `gaming-test`-Pfad diente nur noch als Diagnosecontainer fuer den alten `primary`-Pfad, nicht mehr als Produktziel.

## Warum diese Notiz nicht weitergefuehrt wird

Die fruehere Handoff-Notiz war zu breit und zu gemischt:

- zu viele Zeitstaende in einem Dokument
- zu viele Aussagen, die heute nicht mehr gelten
- zu wenig Trennung zwischen Produktpfad und Diagnosepfad

Deshalb wird sie ab jetzt nur noch als Archivanker behalten.

## Verweise

- `2026-03-24-gaming-station-container-doc.md`
- `2026-03-26-gaming-station-diagnostic-und-fixes.md`
- `2026-03-28-gaming-station-host-runtime-discovery-implementationsplan.md`
