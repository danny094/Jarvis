# Claude Handoff - Gaming Station - 2026-03-24

Archivstatus: Gestoppt und archiviert am 2026-04-01.
Hinweis: Diese Handoff-Notiz bleibt nur noch als historischer Zwischenstand fuer den archivierten `gaming-station`-Zweig erhalten.

## Hinweis zum aktuellen Fokus

Stand: 2026-03-27

> Update 2026-03-27:
> - `runtime-hardware` ist inzwischen live und hat fuer den alten Input-Fall belegt, dass der Container die Geraete sah; der Legacy-Restfehler sass im `primary`-/Xorg-Pfad
> - `gaming-station` laeuft operativ wieder auf dem Host-Bridge-/`secondary`-Pfad
> - der Frischdeploy-Pfad wurde gehaertet
> - `stop` behaelt `gaming-station`, `uninstall` entfernt den gestoppten Container jetzt wirklich
> - die Storage-/Mod-/Library-Pfade wurden lokal weiter entwirrt; alter `SteamLibrary`-Pfad kann als Alias auf die aktive Library zeigen

Diese Handoff-Notiz bleibt als technischer Zwischenstand fuer `gaming-station` relevant.

Der aktuelle Umsetzungsfokus liegt aber jetzt zuerst auf dem generischen `runtime_hardware`-Modul:

- [[23-Runtime-Hardware-Modul-Implementationsplan]]
- [[24-Runtime-Hardware-v0-Installationsvertrag]]

Grund:

- die verbleibenden Hardware-/Input-Probleme im Gaming-Pfad sprechen dafuer, zuerst die fehlende generische Hardware- und Attachment-Schicht in Jarvis aufzubauen
- `gaming-station` soll danach bewusst als erster Realtest fuer das neue Modul dienen, statt weiter nur ueber Spezialfixes gepflegt zu werden

## Ziel

Diese Notiz ist der kompakte Uebergabestand fuer Claude, damit die Arbeit an `gaming-station`, Sunshine, Moonlight und `7 Days to Die` ohne erneute Tiefenanalyse fortgesetzt werden kann.

## Aktueller stabiler Stand

- `gaming-station` wurde frisch recreated und neu deployed.
- Aktiver Container:
  - `336899b68514`
  - `trion_gaming-station_1774354200267_5e3bd9`
- Host-Bridge-Pfad funktioniert:
  - Steam im Container
  - Sunshine auf dem Host
  - Host-Xorg auf `:0`
  - `openbox --sm-disable` als kleiner Host-Window-Manager
- `Steam Big Picture Mode` und Stream laufen.
- Ein PS4-Controller wurde erfolgreich auf dem Host gepairt und im Container sichtbar gemacht.
- `7 Days to Die` startet jetzt grundsaetzlich stabil bis ins Spiel.
- EOS-/Save-/Userdata-Problem ist geloest:
  - persistenter Mount:
    - `/data/services/gaming-station/data/userdata -> /home/default/.local/share`
  - Schreibrechte funktionieren

## Wichtige Runtime-Ressourcen

- RAM:
  - `16g`
- Swap:
  - `24g`
- CPU:
  - `6.0`
- PIDs:
  - `512`

Wichtige Erkenntnis:

- zu wenig RAM war sehr wahrscheinlich der Hauptgrund fuer die fruehen harten Abstuerze
- der spaetere Restfehler ist eher Performance-/Streaming-/Timing-bezogen, nicht mehr der grundlegende Spielstart

## 7 Days to Die

### Was jetzt funktioniert

- `7 Days to Die` (`AppID 251570`) startet ueber Steam bis ins Spiel
- der eigentliche Unity-Client laeuft
- GPU-Rendering funktioniert
- Spielstaende und EOS-Cache koennen jetzt geschrieben werden

### Aktuelle Startlogik

Die Spiel-Startdatei wurde auf einen stabileren Pfad gebracht:

- `/home/default/.steam/steam/steamapps/common/7 Days To Die/7DaysToDie.sh`

Aktueller Kern:

- `unset LD_PRELOAD`
- `unset ENABLE_VK_LAYER_VALVE_steam_overlay_1`
- direkter Start von:
  - `./7DaysToDie.x86_64 -disablenativeinput -nogs "$@"`

`-force-glcore` wurde spaeter wieder entfernt, um Performance nicht unnötig zu bremsen.

### Wichtiger Performance-Befund

Das Spiel fuehlt sich im Stream teils noch unsauber an, aber die internen Spiel-Logs sehen deutlich besser aus:

- Unity-Log:
  - `/home/default/.config/unity3d/The Fun Pimps/7 Days To Die/Player.log`
- dort waehrend des laufenden Spiels:
  - mehrfach knapp `59-60 FPS`

Das heisst:

- das Spiel selbst rendert inzwischen weitgehend sauber
- der verbleibende Performance-Eindruck sitzt eher im Streaming-/Host-Xorg-/Input-/Frametime-Pfad

### Relevante Spiel-Config

Spiel-Prefs:

- `/home/default/.config/unity3d/The Fun Pimps/7 Days To Die/prefs`

Auffaellig:

- `OptionsGfxQualityPreset = 5`
- `OptionsGfxViewDistance = 6`
- `OptionsGfxTreeDistance = 4`
- `OptionsGfxShadowQuality = 3`
- `OptionsGfxObjQuality = 3`
- `OptionsGfxTerrainQuality = 3`
- `OptionsGfxGrassDistance = 3`
- `OptionsGfxVsync = 1`

Das ist eher hoch. Falls weiter an "FPS-Gefuehl" gearbeitet wird, ist ein sinnvoller naechster Schritt:

- Balanced-Profil testen:
  - `QualityPreset 5 -> 4`
  - `ViewDistance 6 -> 4`
  - `ShadowQuality 3 -> 2`
  - `ShadowDistance 2 -> 1`
  - `TreeDistance 4 -> 2 oder 3`

## Sunshine / Streaming

### Aktiver Host-Pfad

- Xsession:
  - `$HOME/.local/bin/host-sunshine-xsession.sh`
- Startscript:
  - `$HOME/.local/bin/start-host-sunshine-session.sh`
- Service:
  - `$HOME/.config/systemd/user/sunshine-host.service`
- Aktiver Sunshine-Config-Pfad:
  - `$HOME/.config/sunshine/host-test/sunshine.conf`

### Aktiver Sunshine-Stand

Aktive Config:

- `encoder = nvenc`
- `hevc_mode = 2`
- `av1_mode = 1`
- `qp = 20`
- `fec_percentage = 0`
- `min_log_level = 2`

Wichtige Einordnung:

- Sunshine laeuft aktiv ueber den `host-test`-Config-Pfad
- die leere Default-Datei unter
  - `$HOME/.config/sunshine/sunshine.conf`
  ist aktuell nicht die relevante Runtime-Datei

### Letzte Härtung

- `fec_percentage` wurde fuer lokales LAN von `5` auf `0` reduziert
- `min_log_level` wurde von `0` auf `2` reduziert
- `openbox` wurde in den lokalen Host-Xsession-Stand nachgezogen

### Encoder-Befund

Aus dem aktiven Sunshine-Log:

- HEVC/NVENC-Pfad ist aktiv
- relevante Logdatei:
  - `$HOME/.local/state/sunshine-host.log`

### Noch auffaellig

Im Host-/Xorg-/Sunshine-Umfeld tauchen weiter Dinge auf, die beobachtet werden sollten:

- wiederkehrende `libinput`-/`InitPointerDeviceStruct()`-Meldungen im User-Journal
- moegliche Input-/Frametime-Reibung

Das ist aktuell plausibler als ein echter Spiel-Crash.

## Moonlight

Wichtige Erkenntnisse:

- `150 Mbps` bei `1080p` ist sehr wahrscheinlich unnötig hoch
- `HEVC` ist korrekt
- `Frame Pacing` kann bei bereits hoher Bitrate zusaetzliche Traegheit erzeugen

Sinnvoller Teststand:

- `HEVC`
- `50 Mbps`
- Decoder `Auto`
- `Frame Pacing` eher aus oder nur vorsichtig testen

## Bluetooth / Controller

- PS4-Controller (`Wireless Controller`) erfolgreich:
  - `Paired`
  - `Bonded`
  - `Trusted`
  - `Connected`
- Host sieht:
  - `/dev/input/js0`
  - `event21` = `Wireless Controller`
  - `event22` = Motion Sensors
  - `event23` = Touchpad
- Der Container sieht diese Input-Geraete ebenfalls.
- Das bedeutet:
  - Host-Pairing ist der richtige Pfad
  - Bluetooth muss nicht in den Container verlagert werden

## Moonlight-Reconnect-Crash

- Ein weiterer Crashpfad wurde klar eingegrenzt:
  - HDMI-TV-Bild + Moonlight-Reconnect kann den Host-Stream crashen
  - das ist kein Firewall-Problem
- Relevante Xorg-Logik:
  - Sunshine erzeugt bei Reconnect virtuelle `Touch passthrough`- und `Pen passthrough`-Input-Geraete
  - Xorg/libinput crasht dann in `InitPointerDeviceStruct()`
  - das DS4-Touchpad ist ein zusaetzlicher Xorg-Input-Kandidat
- Bereits vorbereitet:
  - Paketstand `90-sunshine-headless.conf` ignoriert jetzt
    - `Touch passthrough`
    - `Pen passthrough`
    - `Wireless Controller Touchpad`
  - lokaler User-Service `sunshine-host.service` wurde auf `Restart=always` gehaertet
- Wichtig:
  - `Restart=always` ist lokal sofort aktiv
  - die Xorg-Ignore-Regeln muessen fuer den aktiven Host noch materialisiert werden, weil `/etc/X11/xorg.conf.d/90-sunshine-headless.conf` root-owned ist
  - spaeter trat noch `RTSP handshake failed: error 60` auf:
    - `ufw` war `inactive`
    - `sunshine-host.service` lief dabei sauber
    - das wirkt aktuell eher wie ein staler Moonlight-Session-/Pairing-Zustand als wie ein echter Firewall-Block

## Wichtiger Neustart-Befund

- Ein spaeterer Ausfall von Moonlight/TV war kein Firewall-Thema.
- Reale Ursache:
  - `sunshine-host.service` war down
  - der `gaming-station`-Container war `Exited (137)`
- Die `waiting for udev to die`-Zeilen stammten nur aus dem Container-Shutdownpfad.
- Danach wurde beides wieder sauber gestartet:
  - Container
  - Host-Sunshine-Service
  - Listener auf `47984`, `47989`, `47990`, `48010`

## Frischer Deploy-Status

Der neue lokale Core-Stand ist deutlich naeher an "frischer Deploy funktioniert" als zuvor.

Bewiesen:

- `stop/remove -> fresh deploy` lief erfolgreich
- neuer Container kommt mit den neuen Mounts hoch
- Userdata ist persistent
- Host-Bridge funktioniert
- `7 Days to Die` kommt jetzt bis ins Spiel

## Noch offene Restpunkte

1. Streaming-/Frametime-Gefuehl weiter eingrenzen
- weil das Spiel intern schon ~60 FPS meldet
- Fokus eher auf:
  - Sunshine-/Host-Xorg
  - Input
  - Moonlight-Bitrate/Pacing

2. 7DTD-Grafikprofil sinnvoll absenken
- nicht weil das Spiel kaputt ist
- sondern um die gefuehlte Ingame-Leistung zu glaetten

3. Host-Xorg-Input-Layer beobachten
- die `libinput`-/Xorg-Meldungen sind der sichtbarste Restkandidat

4. Paket-/GitHub-Nachlauf spaeter sauber spiegeln
- lokale Host-Skriptstaende
- Sunshine-Config
- eventuelle weitere Performance-Anpassungen

## Wichtige Dateien fuer Claude

- `<repo-root>/container_commander/mcp_tools.py`
- `<repo-root>/container_commander/host_companions.py`
- `<repo-root>/marketplace/packages/gaming-station/package.json`
- `<repo-root>/marketplace/packages/gaming-station/host/bin/host-sunshine-xsession.sh`
- `<repo-root>/marketplace/packages/gaming-station/host/bin/gaming-station-steam.sh`
- `<repo-root>/marketplace/packages/gaming-station/host/config/sunshine/sunshine.conf`
- `$HOME/.local/bin/host-sunshine-xsession.sh`
- `$HOME/.local/bin/gaming-station-steam.sh`
- `$HOME/.config/sunshine/host-test/sunshine.conf`
- `$HOME/.local/state/sunshine-host.log`
- `/home/default/.config/unity3d/The Fun Pimps/7 Days To Die/Player.log`
- `/home/default/.config/unity3d/The Fun Pimps/7 Days To Die/prefs`
- `/home/default/.steam/steam/steamapps/common/7 Days To Die/7DaysToDie.sh`

## Sichere naechste Schritte

1. Keine erneute Fundament-Reparatur anfangen.
- Der Stack ist jetzt grundsaetzlich funktionsfaehig.

2. Zuerst nur Performance-/Streaming-Tuning.
- Keine grossen Architekturwechsel mehr.

3. Erst Spiel-Preset anpassen, dann erneut testen.

4. Wenn sich das Spiel intern weiter gut verhaelt, aber der Stream nicht:
- Host-Xorg-/Input-/Sunshine-Pfad weiter profilieren
- nicht wieder den Container als Hauptschuldigen behandeln
