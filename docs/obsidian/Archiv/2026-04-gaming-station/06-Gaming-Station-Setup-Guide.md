# Gaming Station Setup Guide

Archivstatus: Gestoppt und archiviert am 2026-04-01.
Hinweis: Dieses Setup-Dokument bleibt nur noch als historische Referenz fuer den eingestellten `gaming-station`-Pfad erhalten.

## Ziel

Diese Notiz beschreibt den pragmatischen Weg, `gaming-station` auf einem anderen System lauffähig zu bekommen, ohne dieselben Fehlannahmen noch einmal zu durchlaufen.

Der wichtigste Architekturpunkt:

- `Steam` bleibt im Container
- `Sunshine` läuft auf dem Host
- `Moonlight` verbindet sich zum Host
- `noVNC` ist nur ein Debug-/Installer-Pfad

## Wann dieses Setup sinnvoll ist

`gaming-station` ist sinnvoll, wenn:

- ein Linux-Host mit NVIDIA-GPU vorhanden ist
- Steam und Spiele in einem verwalteten Container leben sollen
- Streaming an Moonlight gewünscht ist
- persistenter Storage für Spiele und Config vorhanden ist

Weniger sinnvoll ist es, wenn:

- unbedingt `Sunshine im Container` erzwungen werden soll
- kein sauberer Host-Displaypfad aufgebaut werden kann
- keinerlei persistenter Storage für große Spieledaten vorhanden ist

## Empfohlene Zielarchitektur

### Host

- hält `Xorg :0`
- hält `Sunshine`
- hält Capture- und NVENC-Pfad
- liefert den Stream an Moonlight

### Container

- hält Steam
- hält Steam-User-State
- hält Spielebibliothek und App-Logik
- rendert auf den Host-Xorg
- hält `~/.steam` auf persistentem Storage, nicht nur die Library

### Debugpfad

- `noVNC` nur für Installer, Sichtprüfung und einfache GUI-Debugs

## Installationsmodell

`gaming-station` sollte langfristig nicht als fest verdrahteter Core-Bestandteil verstanden werden, sondern als optionales `Marketplace`-/`Shop`-Paket.

Pragmatischer Aufbau des Pakets:

- Container-Blueprint
- Host-Companion für Sunshine/Xorg/uinput
- Storage-Layout
- optionaler Binary-Bootstrap für `sunshine`

Warum das sinnvoll ist:

- nur Nutzer mit echtem Gaming-Bedarf installieren es
- der TRION-Core bleibt von Gaming-Spezialfällen entkoppelt
- Host-Dateien und Services sind sauber paketiert
- Repair- und Fresh-Install-Pfade werden dadurch realistischer

## Wichtige Voraussetzungen

1. NVIDIA-GPU mit funktionierendem Treiber auf dem Host
2. persistenter Storage für `/data`
3. Hostseitiger X11-/Displaypfad
4. funktionsfähiges hostnahes Sunshine
5. ein kleiner Host-Window-Manager fuer die X-Session, z. B. `openbox`
6. erst danach der `gaming-station`-Container

## Bekannte Stolperstellen

### 1. Sunshine im Container

Bei NVIDIA ist `Sunshine im Container` schnell problematisch:

- WebUI erreichbar bedeutet noch nicht, dass Capture funktioniert
- noVNC und Sunshine teilen sich nicht automatisch denselben brauchbaren Displaypfad
- Dummy-/virtuelle Displays helfen oft für Sichtbarkeit, aber nicht automatisch für Moonlight-Streaming

Pragmatischer Weg:

- Sunshine auf den Host legen

### 2. noVNC falsch einordnen

noVNC ist hilfreich, aber nur für:

- Installer
- GUI-Sichtprüfung
- Debugging

noVNC ist nicht automatisch der beste Gaming-Pfad.

### 3. Falscher Host-Modus

Der Host sollte für TV-/Moonlight-Nutzung auf einem sauberen `16:9`-Modus laufen:

- empfohlen: `1920x1080`

Ein Modus wie `1920x1200` kann dazu führen, dass:

- Steam klein wirkt
- Big Picture letterboxed aussieht
- das Bild matschig oder falsch skaliert erscheint

### 4. Steam Big Picture startet nicht wirklich fullscreen

Auch wenn der Host korrekt auf `1920x1080` läuft, kann Big Picture zunächst nur als kleines Fenster starten, z. B. `1280x800`.

Dann sieht der Stream wie ein kleines zentriertes Bild mit schwarzen Rändern aus.

Pragmatischer Fix:

- Big Picture beim Start aktiv auf `1920x1080` ziehen
- wenn die Host-X-Session ganz ohne Window Manager laeuft, reicht das allein nicht immer
- in der Praxis war ein kleiner Host-Window-Manager wie `openbox` noetig, damit das Fenster wirklich sauber fullscreen wird

### 5. Storage falsch platziert

Große Daten gehören nicht nur ins Container-Dateisystem.

Wichtig:

- Steam-Library auf persistenten Storage wie `/data`
- Config und dauerhafte Zustände ebenfalls bewusst auf persistente Pfade legen
- besonders wichtig: `~/.steam` selbst persistent binden, nicht nur `steamapps`

Wenn nur die Library persistent ist, aber das eigentliche Steam-Home nicht, kann Debian `steam` nach einem Restart wieder in den Installerpfad fallen.

### 6. Stop-Verhalten

Für `gaming-station` ist normales `Stop` als `Stop and preserve` sinnvoller als `Stop and delete`.

Warum:

- Steam-/Home-/Session-State bleibt erhalten
- Neustarts und spätere Wiederaufnahme werden einfacher
- das Verhalten passt besser zu einem dauerhaften Service

### 7. Blueprint-Generationen sauber halten

Bei Dockerfile-basierten Blueprints reicht ein statisches `latest`-Image oft nicht.

Wichtig:

- neue Blueprint-Stände sollten nicht unbemerkt auf einem alten Image weiterlaufen
- preserved Container können sonst eine ältere Generation weiterziehen
- für `gaming-station` wurden deshalb content-basierte Image-Tags eingeführt

Praktischer Nutzen:

- der laufende Container passt sichtbar zum aktuellen Blueprint-Stand
- Host-Bridge-Fixes und Persistenzänderungen landen reproduzierbar in neuen Deployments

## Empfohlene Reihenfolge für neue Nutzer

1. Host-GPU und Treiber sauber prüfen
2. Persistenten Storage für `/data` vorbereiten
3. Host-Xorg-/Displaypfad funktionsfähig aufsetzen
4. Host-Sunshine testen
5. `gaming-station` als Host-Bridge-Container deployen
6. Steam-Library **und** `~/.steam` auf persistenten Storage legen
7. einmal echten `stop -> start` testen
8. Big Picture und Moonlight-Auflösung feinjustieren

## Was andere Nutzer direkt wissen sollten

- Das Setup ist kein reiner „Gaming-Container“, sondern ein Host-/Container-Hybrid.
- Für einen wirklich sauberen Fresh-Install ist ein Paketmodell mit `Blueprint + Host Companion` sinnvoller als manuelle Host-Nacharbeit.
- Ein erfolgreicher `stop -> start` ist ein echter Stabilitätstest. Wenn danach wieder ein Steam-Installer auftaucht, fehlt meist Persistenz im eigentlichen Steam-Home oder es läuft noch eine alte Container-Generation.
- Wenn Moonlight kein gutes Bild zeigt, ist oft nicht das Netzwerk das Problem, sondern:
  - falsche Host-Auflösung
  - falscher UI-Modus in Steam
  - falscher Codec-/Client-Pfad
- Eine erreichbare Sunshine-WebUI bedeutet nicht automatisch, dass Streaming korrekt funktioniert.
- Wenn Pairing seltsam hängt, kann auch die konkrete Sunshine-Version relevant sein.

## Aktueller Fresh-Install-Stand

Der Paketpfad ist deutlich weiter als am Anfang, aber noch nicht vollständig “ein Klick und fertig”.

Bereits vorhanden:

- `composite_addon`-Bundle für `gaming-station`
- Host-Companion-Materialisierung über `storage-host-helper`
- `binary_bootstrap` für `sunshine`
- erfolgreicher echter GitHub-`install -> deploy`-Pfad bis zum streambaren Host-Bridge-Container
- sicherer `shadow install`-Pfad zum Testen ohne Eingriff in den Live-Service
- kontrollierter lokaler Marketplace-Install gegen einen temporären Shadow-Bundle-Pfad

Wichtige Zwischen-Erkenntnis:

- der Bundle-/Marketplace-Pfad muss echte Roundtrip-Tests haben
- ein realer Test hat gezeigt, dass YAML-Exports keine Python-spezifischen Typ-Tags enthalten dürfen
- dieser Fehler ist inzwischen behoben, gehört aber genau zu den Dingen, die man bei Fresh-Install-/Marketplace-Logik früh testen muss

Noch offen:

- `openbox` oder ein aequivalenter Window Manager sauber als Host-Abhaengigkeit des Addons deklarieren und automatisiert mitprovisionieren
- sauberer automatischer Start-/Repair-Flow fuer den Host-Companion
- anschliessender produktiver Marketplace-Installflow

## Relevante interne Referenzen

- [[02-Gaming-Station-Storage-Sunshine-noVNC]]
- [[05-Open-Issues-Next-Steps]]
- [[2026-03-23-gaming-station-sunshine-handoff]]
