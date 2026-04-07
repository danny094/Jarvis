# Gaming Station: Sunshine als optionale Abhaengigkeit

Stand dieser Notiz: 2026-03-28
Status: Gestoppt und archiviert am 2026-04-01. Historisch, durch spaeteren Scope ersetzt.

Hinweis: Der zugehoerige `gaming-station`-Pfad ist eingestellt und nur noch archiviert dokumentiert.

## Kurzfassung

Diese Notiz beschrieb einen Zwischenplan, in dem `gaming-station` Sunshine noch als optionale, aber weiterhin teils mutierend behandelte Host-Abhaengigkeit fuehren sollte.

Dieser Plan ist nicht mehr das Zielmodell.

## Was daran heute ueberholt ist

Die alte Idee war:

- Host-Companion bleibt der Hauptpfad
- Sunshine kann optional sein
- Host-seitige Materialisierung bleibt grundsaetzlich erhalten
- bestimmte Streaming-Checks werden nur advisory

Der spaetere Produktentscheid hat das ersetzt durch:

- `gaming-station` startet keinen Host-Installpfad mehr
- `gaming-station` schreibt keine Host-Dateien fuer Sunshine mehr
- `gaming-station` fuehrt kein Host-`enable/start` mehr aus
- der Deploy erkennt Sunshine nur noch read-only und meldet den Befund

## Gueltiger Nachfolger

Massgeblich ist jetzt:

- `2026-03-28-gaming-station-host-runtime-discovery-implementationsplan.md`

Dort ist der spaetere und heute gueltige Scope dokumentiert:

- weg von Host-Mutation
- hin zu Host-Runtime-Discovery

## Warum diese Notiz erhalten bleibt

Sie zeigt den Zwischenschritt in der Entscheidungsfindung:

- von "Sunshine weiterhin hostseitig materialisieren, aber optional machen"
- hin zu "Sunshine fuer `gaming-station` nur noch erkennen und melden"

Als Implementationsgrundlage soll sie aber nicht mehr verwendet werden.
