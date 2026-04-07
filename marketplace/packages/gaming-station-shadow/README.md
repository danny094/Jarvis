# Gaming Station Shadow Composite Addon

Dieses Paket beschreibt einen sicheren Shadow-Install fuer `gaming-station`:

- `gaming-station`-Blueprint bleibt unveraendert
- `sunshine-host-shadow` materialisiert nur parallele Host-Dateien mit Shadow-Namen

## Ziel

Das Paket dient als Live-Test des Composite-Installweges, ohne den laufenden `sunshine-host.service` zu beruehren.

## Enthaltene Host-Bausteine

- User-Service fuer hostnahes Sunshine
- X11-Session-Skripte
- uinput-/DRI-Prepare-Skript
- Xorg-Headless-Konfiguration
- EDID-Asset in textueller Hex-Form

## Wichtige Architekturentscheidung

- Steam bleibt im Container
- Sunshine laeuft auf dem Host
- Storage und Steam-Home bleiben unter `/data/services/gaming-station/...`

## Aktueller Status

Die Dateien werden in parallele `*-shadow`-Pfade materialisiert und nicht automatisch gestartet.
