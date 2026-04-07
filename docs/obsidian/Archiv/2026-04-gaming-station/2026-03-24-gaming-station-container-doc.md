# Gaming-Station Container — Dokumentation

Stand: 2026-03-28

Archivstatus: Gestoppt und archiviert am 2026-04-01.
Hinweis: Diese Notiz beschreibt den zuletzt dokumentierten `gaming-station`-Stand eines inzwischen gestoppten und archivierten Gaming-Container-Pfads.

> Diese Notiz fuehrt den **aktuellen operativen Stand**. Aeltere `primary`-/Container-Sunshine-Zwischenstaende sind historisch und nicht mehr das Zielbild.
> Architekturentscheidung ab 2026-03-28:
> `gaming-station` bleibt Host-Bridge-/`MODE=secondary`, aber der Blueprint soll kuenftig den Host **nicht mehr** fuer Sunshine materialisieren oder veraendern.
> Zielbild fuer den Produktpfad ist damit:
> - Steam/App-State im Container
> - Sunshine ausserhalb des Containers auf dem Host
> - der Deploy meldet nur noch `Sunshine auf dem Host gefunden` oder `Sunshine auf dem Host nicht gefunden`
> - keine automatische Host-Installation, kein Host-Service-Write, kein `systemctl --user enable/start`

## Leseordnung

Wenn jemand `gaming-station` neu versteht, nur noch so lesen:

1. Diese Notiz
   Operativer Ist-Stand.
2. `2026-03-26-gaming-station-diagnostic-und-fixes.md`
   Belegte Fehlerkette und Fix-Historie.
3. `2026-03-28-gaming-station-host-runtime-discovery-implementationsplan.md`
   Scope-Wechsel und Umsetzungsstand.
4. `2026-03-28-gaming-station-games-storage-integration-plan.md`
   Zielintegration fuer `games`-Datentraeger ueber Storage-Broker + Commander.
5. `2026-03-28-filestash-storage-broker-simple-blueprint-implementationsplan.md`
   Referenzdienst fuer den generischen Storage-Produktpfad ausserhalb von `gaming-station`.

Nicht mehr kanonisch:

- `2026-03-23-gaming-station-sunshine-handoff.md`
- `2026-03-25-gaming-station-sunshine-optional.md`

---

## Ueberblick

| Feld | Wert |
|------|------|
| Architektur | Host-Bridge / `MODE=secondary` |
| Streaming | Sunshine auf dem Host, read-only entdeckt |
| Container-Rolle | Steam, Spiele, App-State |
| Display | Host-Xorg `:0` |
| Audio | Host-Pulse via Bind-Mount |
| GPU | NVIDIA-Pfad aktiv, `NVIDIA_VISIBLE_DEVICES=all`, `NVIDIA_DRIVER_CAPABILITIES=all` |
| Netzwerk | `bridge` fuer den Container, Sunshine-Ports hostseitig |
| Blueprint | `gaming-station` (Marketplace-Paket, hostnaher Deploy-Pfad) |

---

## Recovery-Snapshot

Diese Sektion ist der **autoritative Wiederaufbau-Stand** des derzeit funktionierenden Containers.

Snapshot:

- Container-Name:
  - `trion_gaming-station_1774739490165_6b6567`
- Container-ID:
  - `1ba28f4ef7a58fad66b73ffb6016c76c8bb3871eda55820a72a123cfe64f187d`
- erstellt:
  - `2026-03-28T23:11:30Z`
- Image-Tag:
  - `trion/gaming-station:ec70029a5480`
- Host-Sunshine-Service:
  - `sunshine-host.service`
  - aktiv seit `2026-03-28 12:49:03 UTC`

### Exakte Laufparameter

- `NetworkMode=bridge`
- `IpcMode=host`
- `Runtime=nvidia`
- `Privileged=true`
- `CapAdd=[NET_ADMIN, SYS_ADMIN, SYS_NICE]`
- `SecurityOpt=[seccomp=unconfined, apparmor=unconfined, label=disable]`
- `Memory=16g`
- `MemorySwap=24g`
- `CPU=6.0`
- `PidsLimit=512`

### Exakte Devices

- `/dev/dri`
- `/dev/uinput`
- `/dev/input`

### Exakte Mounts

Wichtiger Live-Befund:

- Der aktuell funktionierende Container nutzt hier **Docker-Volumes** fuer `/config` und `/data`.
- Fuer einen identischen Wiederaufbau ist deshalb diese Tabelle wichtiger als aeltere Sollbilder unter `/data/services/gaming-station/...`.

| Typ | Source | Ziel |
|-----|--------|------|
| `volume` | `gaming_steam_config` | `/config` |
| `volume` | `gaming_steam_data` | `/data` |
| `volume` | `gaming_user_data` | `/home/default/.local/share` |
| `volume` | `gaming_steam_home` | `/home/default/.steam` |
| `volume` | `trion_ws_gaming-station_1774739490165_6b6567` | `/workspace` |
| `bind` | `/tmp/.X11-unix` | `/tmp/.X11-unix` |
| `bind` | `/run/user/1000/pulse` | `/tmp/host-pulse` |
| `bind` | `/mnt/games/services/gaming-station-games/data` | `/games` |

### Exakte Kern-Env

- `MODE=secondary`
- `DISPLAY=:0`
- `TRION_HOST_DISPLAY_BRIDGE=true`
- `ENABLE_SUNSHINE=false`
- `PULSE_SERVER=unix:/tmp/host-pulse/native`
- `NVIDIA_VISIBLE_DEVICES=all`
- `NVIDIA_DRIVER_CAPABILITIES=all`
- `DISPLAY_SIZEW=1920`
- `DISPLAY_SIZEH=1080`
- `DISPLAY_REFRESH=120`
- `ENABLE_EVDEV_INPUTS=true`
- `STEAM_USER` / `STEAM_PASS` werden aus Vault/Deploy-Env befuellt

### Erwarteter Supervisor-Zustand

Im funktionierenden Host-Bridge-Stand:

- `desktop RUNNING`
- `steam RUNNING`
- `udev RUNNING`
- `dbus STOPPED`
- `polkit STOPPED`
- `xorg STOPPED`
- `xvfb STOPPED`
- `sunshine STOPPED`

Das ist hier korrekt:

- Xorg und Sunshine laufen auf dem Host
- Desktop und Steam laufen im Container

### Erwarteter sichtbarer Zustand auf `DISPLAY=:0`

Nach frischem Start:

- `xfce4-panel`
- `xfdesktop`
- nach erstem Steam-Update:
  - `steamwebhelper.steam`
  - Fenstertitel: `Sign in to Steam`

### Host-Komponenten

Massgebliche Host-Dateien fuer denselben Stand:

- `$HOME/.config/systemd/user/sunshine-host.service`
- `$HOME/.local/bin/host-sunshine-xsession.sh`
- `$HOME/.local/bin/gaming-station-steam.sh`
- `$HOME/.config/sunshine/host/sunshine.conf`
- `$HOME/.local/opt/sunshine/sunshine.AppImage`

### Wichtige Recovery-Warnung

Der funktionierende Live-Stand ist jetzt wieder mit expliziter Persistenz fuer Steam/Userdata belegt:

- `/home/default/.steam` ist ein eigenes Docker-Volume:
  - `gaming_steam_home`
- `/home/default/.local/share` ist ein eigenes Docker-Volume:
  - `gaming_user_data`
- `/games` kommt ueber den generischen `mount_ref`-Pfad:
  - `container::mount_ref::gaming-station-games -> /games`
- im frischen Steam-Home existiert aktuell `config.vdf`, aber noch kein `loginusers.vdf`
- deshalb ist der aktuelle sichtbare Restzustand `Sign in to Steam`

Wenn das Ziel lautet:

- **denselben funktionierenden Stand wiederherstellen**
  - diesen Snapshot exakt nachbauen
- **danach saubere Persistenz nachziehen**
  - erst im zweiten Schritt Storage/Persistenz umbauen

### Storage-Update 2026-03-28

Der Games-Datentraeger ist inzwischen separat live integriert:

- Partition:
  - `/dev/sdd1`
- Dateisystem:
  - `ext4`
- Label:
  - `games`
- Host-Mount:
  - `/mnt/games`
- `/etc/fstab`:
  - UUID-basierter persistenter Eintrag fuer `/mnt/games`
- provisionierter Service-Pfad:
  - `/mnt/games/services/gaming-station-games/data`
- publizierter Commander-Asset:
  - `gaming-station-games`
- Container-Zielpfad:
  - `/games`

Live-Befund im aktuellen Produktcontainer:

- `/games` ist `ext4`, Quelle `/dev/sdd1`
- `/home/default/.steam` ist ein expliziter Volume-Mount
- `/home/default/.local/share` ist ein expliziter Volume-Mount
- `desktop` und `steam` laufen beide
- der normale Fresh-Deploypfad kommt wieder ohne Postcheck-Bypass hoch

Zusaetzlicher Produktstatus ausserhalb von `gaming-station`:

- der generische Referenzpfad `storage-broker -> storage asset -> runtime-hardware mount_ref -> Simple Blueprint -> Docker-Bind-Mount`
  - ist inzwischen live belegt
- Referenzdienst:
  - `Filestash`
- Referenz-Smoke-Test:
  - ein Wegwerf-Blueprint mit `container::mount_ref::gaming-station-games`
  - wurde direkt nach `/storage/gaming-station-games` materialisiert
  - Schreibtest im laufenden Container war erfolgreich

Damit ist klar getrennt:

- der generische Storage-Produktpfad funktioniert
- `gaming-station` haengt fuer `games` funktional nicht mehr am Storage-Broker-/Simple-Blueprint-Grundproblem
- der verbleibende Rest bei `gaming-station` ist vor allem Sonderlogik-/Postcheck-Drift

Update 2026-03-28:

- der gespeicherte `gaming-station`-Blueprint wurde inzwischen auf den generischen `mount_ref`-Produktpfad umgestellt
- fuer `games` bleibt der Container-Zielpfad:
  - `/games`
- aber der Mount kommt fuer neue Deploys jetzt ueber:
  - `hardware_intents -> container::mount_ref::gaming-station-games -> /games`
- der statische `/games`-Bind-Mount ist aus dem Blueprint entfernt
- der aktuell laufende verifizierte `gaming-station`-Container wurde dabei bewusst nicht neu deployed

Bedeutung dieser beiden Postchecks im aktuellen Code:

- `steam_home_persistent` bedeutet derzeit **nur**:
  - `/home/default/.steam` muss exakt von `/data/services/gaming-station/data/steam-home` kommen
- `user_data_persistent` bedeutet derzeit **nur**:
  - `/home/default/.local/share` muss exakt von `/data/services/gaming-station/data/userdata` kommen

Wichtig:

- das sind aktuell **strikte Struktur-Checks**
- das sind **keine** allgemeinen Funktions-Checks fuer "Steam-Daten sind irgendwie persistent"
- im heutigen Live-Stand mit Docker-Volume auf `/data` und ohne diese beiden separaten Host-Binds schlagen sie deshalb erwartbar fehl
- der aktuelle Restfehler ist damit ein Drift zwischen altem Persistenz-Sollbild und heutigem Runtime-Aufbau

---

## Aktuelle Architektur

- Der Container startet mit `MODE=secondary`.
- Sunshine laeuft **nicht** mehr im Container, sondern hostseitig ueber `sunshine-host.service`.
- Der Deploy prueft Host-Sunshine nur noch read-only ueber Host-Runtime-Discovery.
- Steam und Spiele laufen im Container, rendern aber auf den Host-Display-Pfad.

Publish-Hinweis 2026-04-07: Benutzerbezogene Host-Pfade wurden fuer das oeffentliche Repo auf `$HOME`-basierte Platzhalter reduziert.

## TODO-Ueberblick

Die grossen Architekturentscheidungen stehen, aber folgende Produktluecken sind noch offen:

- Host-Runtime-Discovery weiter ent-hardcoden
  - weg von `danny`, `1000`, festen `$HOME/...`-Pfaden und festen Sunshine-Service-Namen
- den historischen `gaming-station`-Altbestand fuer mutierende Host-Companions sauber vom Produktpfad trennen
- den Storage-Broker- und `runtime-hardware`-Pfad fuer neue Datentraeger als echten Standard-Flow schliessen
  - Datentraeger anlegen
  - Asset publizieren
  - im Simple Blueprint auswaehlen
  - als nutzbaren Mount deployen
- `gaming-station` langfristig vom heutigen Games-Sonderpfad auf den generischen `mount_ref`-/Blueprint-Produktpfad ziehen
- die alten Persistenz-Postchecks an den heutigen Produktpfad anpassen

Wichtige Scope-Klarstellung:

- Das oben ist der **aktuelle Live-Stand**.
- Der **naechste Produkt-Scope** aendert nur den Host-Integrationspfad:
  - `gaming-station` soll Host-Sunshine nur noch entdecken und melden
- `gaming-station` soll Host-Sunshine nicht mehr selbst installieren oder starten
- Dafuer ist ein eigener Implementationsplan angelegt:
  - `2026-03-28-gaming-station-host-runtime-discovery-implementationsplan.md`
- Der naechste Storage-Ausbau fuer eine echte Spielebibliothek ist separat dokumentiert:
  - `2026-03-28-gaming-station-games-storage-integration-plan.md`

Wichtige Env-Werte:

| Variable | Wert |
|----------|------|
| `MODE` | `secondary` |
| `DISPLAY` | `:0` |
| `TRION_HOST_DISPLAY_BRIDGE` | `true` |
| `ENABLE_SUNSHINE` | `false` |
| `PULSE_SERVER` | `unix:/tmp/host-pulse/native` |

Wichtiger Live-Drift:

- Der gespeicherte Commander-Blueprint ist nicht 1:1 derselbe wie der aktuell funktionierende Containerzustand.
- Der laufende Container bindet `/config` und `/data` aktuell ueber Docker-Volumes, nicht ueber direkte Hostpfade unter `/data/services/gaming-station/...`.
- Fuer Recovery des funktionierenden Zustands ist deshalb die Sektion `Recovery-Snapshot` oben massgeblich.

---

## Mounts & Persistenz

Wichtig:

- Diese Sektion beschreibt den geplanten bzw. gewuenschten Persistenzpfad.
- Fuer den exakten Wiederaufbau des **heute funktionierenden** Containers gilt zunaechst der `Recovery-Snapshot` oben.

| Host-Pfad | Container-Pfad | Zweck |
|-----------|---------------|-------|
| `/data/services/gaming-station/config` | `/config` | Paket-/App-Konfig |
| `/data/services/gaming-station/data` | `/data` | allgemeine persistente Daten |
| `/data/services/gaming-station/data/steam-home` | `/home/default/.steam` | aktive Steam-Library |
| `/data/services/gaming-station/data/userdata` | `/home/default/.local/share` | Savegames, Unity-/EOS-/Userdaten |
| `/mnt/games/services/gaming-station-games/data` | `/games` | separate Steam-/Spielebibliothek ueber Storage-Broker |
| `/tmp/.X11-unix` | `/tmp/.X11-unix` | Host-X11-Bridge |
| `/run/user/1000/pulse` | `/tmp/host-pulse` | Host-Pulse-Bridge |
| `trion_ws_gaming-station_*` | `/workspace` | TRION Workspace |

Wichtig:

- Spiele-/Steam-Daten bleiben unter `/data/services/gaming-station/...` persistent.
- Die fruehere Verwirrung zwischen alter `config/SteamLibrary` und aktiver Steam-Library wurde lokal entschaerft:
  - die aktive Library ist `data/steam-home`
  - `config/SteamLibrary` kann als Alias/Symlink auf die aktive Library zeigen

---

## Host-Integration

Historisch vorhandene Host-Dateien:

- `$HOME/.config/systemd/user/sunshine-host.service`
- `$HOME/.local/bin/host-sunshine-xsession.sh`
- `$HOME/.local/bin/start-host-sunshine-session.sh`
- `$HOME/.local/bin/gaming-station-steam.sh`

Bootstrap-Stand:

- Sunshine wird fuer frische Installationen standardmaessig ueber ein AppImage unter
  `$HOME/.local/opt/sunshine/sunshine.AppImage`
  bereitgestellt.
- Der Frischdeploy-Pfad wurde live gegen geloeschte lokale Host-Artefakte validiert.

Produktpfad heute:

- Dieser mutierende Host-Companion-Pfad gilt nicht mehr als Ziel fuer den Marketplace-/Produktpfad.
- Fuer `gaming-station` ist der Produktpfad auf **read-only Host-Runtime-Discovery** umgestellt.
- Die oben genannten Host-Dateien bleiben als lokaler Alt-/Uebergangsbestand relevant, werden vom aktuellen Deploy aber nicht mehr neu materialisiert.

---

## Commander-Verhalten

- `gaming-station` bleibt weiterhin `preserve on stop`.
- Der Commander unterscheidet jetzt sauber:
  - `Stop` = Container gestoppt, aber erhalten
  - `Uninstall` = gestoppten Container wirklich entfernen
- Bei Paketen mit Host-Companion wird beim echten `uninstall` zusaetzlich der Host-Service mit aufgeraeumt.
- `/data/services/...` bleibt dabei bewusst erhalten.

Aktiver Scope:

- `gaming-station` materialisiert im Produktpfad keinen Host-Companion mehr.
- Deploys pruefen den Host nur noch read-only und haengen den Befund als Status/Warnung an.

---

## Deploy-Reife

Aktueller Urteilstand:

- fuer frische Deploys **operativ nutzbar, aber noch nicht fertig**
- NVIDIA-Pfad **sehr wahrscheinlich lauffaehig**
- Host-Bridge-Pfad ist deutlich stabiler als der alte Legacy-`primary`-Containerpfad

Bereits live verifiziert:

- frischer Redeploy
- Host-Companion materialisiert neu
- Steam startet im Container
- Moonlight-/Sunshine-Grundpfad funktioniert
- Maus funktioniert wieder im Host-Bridge-Pfad
- spaeter am 2026-03-28 nach dem Scope-Wechsel auf read-only Host-Runtime-Discovery:
  - der Engine-/Host-Helper-Pfad erkennt `sunshine-host.service` auf dem Host wieder als aktiv
  - `gaming-station` deployt ohne neue Host-Mutation
  - die Maus funktioniert in diesem Stand wieder
  - zunaechst erschienen im Stream weder Desktop noch Steam
  - der Restpunkt lag damit nicht mehr bei der Maus selbst, sondern im sichtbaren Desktop-/App-Startpfad
  - spaeter am selben Tag wurde der `secondary`-Desktop-Pfad weiter gehaertet:
    - `desktop` autostartet im Container wieder
    - der blockierende First-Run-`xterm` fuer Flatpak-Install wird im Host-Bridge-Pfad uebersprungen
    - Steam wartet auf den Desktop-Marker, statt vor der Session zu starten
    - `xfwm4` uebernimmt den Window-Manager-Slot per `--replace`, damit Host-`openbox` den Container-Desktop nicht mehr blockiert
  - frischer Live-Deploy `trion_gaming-station_1774703243545_47e308` belegt danach:
    - `desktop` und `steam` laufen beide
    - auf `DISPLAY=:0` erscheinen `xfce4-panel`, `xfdesktop` und spaeter ein sichtbares Steam-Fenster
    - nach dem ersten Steam-Update ist das sichtbare Fenster aktuell `Sign in to Steam`
  - der sichtbare Desktop-/WM-Pfad ist damit fuer den Host-Bridge-Deploy wieder da
  - der verbleibende Rest sitzt jetzt im Steam-Login-/Account-Zustand, nicht mehr im Desktop-Start selbst
- fuer einen separaten `gaming-test`-Blueprint mit eigenem Dockerfile wurde zusaetzlich live verifiziert:
  - der fruehere Init-Abbruch `mount: /proc: permission denied` kam nicht vom Storage-Broker
  - Ursache war das Base-Image `josh5/steam-headless`, genauer `/etc/cont-init.d/80-configure_flatpak.sh`
  - der abgeleitete Dockerfile-Pfad patched diesen Schritt jetzt so, dass in unprivilegierten Containern nur noch `Skipping Flatpak proc remount in unprivileged container` geloggt wird
  - derselbe Test-Deploy haengt bei explizitem Opt-in jetzt `/dev/sdd1` auch real als Docker-Device (`rwm`) an den Container
  - der manuelle `gaming-test`-Pfad hatte danach noch einen echten Drift zwischen Generator-Stand und gespeichertem Blueprint-Dockerfile
  - Beleg dafuer war, dass derselbe Blueprint wiederholt mit aelteren content-addressed Tags lief und dadurch neue Patches nicht im Container ankamen
  - der `gaming-test`-Blueprint wurde daraufhin explizit im Store auf den aktuellen Generatorstand gezogen und frisch neu gebaut
  - der Debian-/`zenity`-Steam-Installer ist in diesem manuellen `primary`-Pfad jetzt ebenfalls entfernt
  - das von `nvidia-xconfig` erzeugte `xorg.conf` wird dort jetzt nachbearbeitet:
    - keine statischen `Mouse0`-/`Keyboard0`-Sektionen mehr
    - `AutoAddDevices=true`
    - `AutoEnableDevices=true`
    - Ignore-Regeln fuer `Touch passthrough`, `Pen passthrough` und `Wireless Controller Touchpad`
  - der `primary`-Pfad faellt ausserdem nicht mehr falsch auf `dumb-udev` zurueck:
    - `/run/udev` und `/run/udev/data` werden vor dem alten Image-Check explizit angelegt
    - im Live-Container laeuft jetzt echtes `systemd-udevd`, nicht mehr nur der Dummy-Pfad
  - fuer Sunshine-Passthrough-Devices wurde zusaetzlich eine gezielte spaete udev-Regel ergaenzt:
    - `Mouse passthrough`
    - `Mouse passthrough (absolute)`
    - `Keyboard passthrough`
    - diese Regel setzt auf den Event-Nodes jetzt explizit `ID_SEAT=seat0` und `TAG+=seat`
  - spaeter am 2026-03-28 wurde fuer denselben `gaming-test`-Pfad ausserdem der Deploy-Pfad selbst repariert:
    - `runtime-hardware` loeste `input` jetzt korrekt als Bind-Mount `/dev/input -> /dev/input` auf
    - der Commander blockierte diesen korrekten Hardware-Bind zunaechst noch faelschlich an `storage_scope`
    - Root Cause war die generische Storage-Scope-Pruefung, die jeden Bind-Mount wie persistenten Storage behandelte
    - `container_commander/storage_scope.py` unterscheidet jetzt generisch zwischen
      - persistenten Storage-Binds
      - systemnahen Runtime-/Hardware-Binds
    - fuer bekannte Runtime-Namensraeume wie `/dev`, `/proc`, `/sys`, `/run/udev`, `/run/dbus`, `/run/user`, `/var/run/dbus`, `/tmp/.X11-unix` gilt jetzt:
      - nur bei identischem Host-/Container-Pfad
      - nur ohne `asset_id`
      - dann keine Storage-Scope-Blockade
    - ein frischer Live-Deploy lief danach wieder mit
      - `hardware_resolution_preview.supported=true`
      - `mount_override_count=1`
      - echtem Docker-Bind-Mount fuer `/dev/input`
      - identischer Inode auf Host und im Container (`142`)

---

## Bekannte Restpunkte

### Gaming / Runtime

- `accounts-daemon` / `polkit` koennen im Container weiter als nicht-blockierende Nebengeraeusche auftauchen.
- Alte Spielstaende oder modabhaengige Saves koennen weiterhin app-spezifisch Probleme machen.
- Neuer Live-Befund Ende 2026-03-28 im echten `gaming-station`-Host-Bridge-Pfad:
  - Sunshine wird ueber den neuen read-only Host-Runtime-Discovery-Pfad wieder als vorhanden erkannt
  - die Maus funktioniert wieder
  - Desktop ist im frischen `secondary`-Deploy wieder sichtbar
  - Steam startet wieder und erzeugt nach dem ersten Updatezyklus erneut ein sichtbares Fenster
  - der aktuelle sichtbare Rest ist `Sign in to Steam`
  - es gibt im frischen Steam-Home derzeit nur `config.vdf`, aber noch kein `loginusers.vdf`
  - der verbleibende Rest liegt damit beim Login-/Persistenzzustand von Steam, nicht mehr bei Desktop/Xorg/WM
- `gaming-station` fuehrt aktuell noch keinen zusaetzlichen Spiele-Datentraeger fuer `games` in den Container:
  - aktuell gibt es fuer `games` noch keinen publizierten `mount_ref`-Assetpfad
  - `/dev/sdd1` ist bisher nur im separaten `block_device_ref`-/`gaming-test`-Diagnosepfad belegt
  - fuer den Produktpfad ist ein spaeterer `mount_ref`-basierter Games-Pfad sauberer als ein Roh-Device-Attach
- `runtime-hardware` hat gezeigt:
  - Host sieht Input-Geraete
  - Container sieht Input-Geraete
  - der alte Restfehler sass im Legacy-`primary`-/Xorg-Pfad, nicht mehr im bloessen Passthrough
- fuer den separaten `gaming-test`-Blueprint bleibt ein eigener Rest sichtbar:
  - `block_device_ref /dev/sdd1` laesst sich jetzt ueber den Deploy-Opt-in real andocken
  - die fruehere `resource_not_found`-Klasse fuer `input`, `usb` und mehrere `device`-Eintraege ist fuer neue Deploys nicht mehr der operative Stand
  - der eigentliche Folgefehler lag in der Scope-Blockade fuer den korrekten `/dev/input`-Bind und ist jetzt behoben
  - der Rest sitzt fuer diesen separaten `primary`-Testpfad damit wieder enger im Live-Input-/Xorg-Hotplug selbst
  - Live-Befund Ende 2026-03-28:
    - frischer Deploy `trion_gaming-test_1774698532404_0b8277` laeuft mit echtem `/dev/input`-Bind
    - `docker inspect` zeigt `/dev/input` unter `Mounts`, nicht mehr unter `HostConfig.Devices`
    - Host- und Container-Inode fuer `/dev/input` sind identisch (`142`)
    - `event21` / `event22` / `event23` tragen jetzt auf den echten Event-Nodes `ID_SEAT=seat0` und `G:seat`
    - `udevadm monitor --kernel --udev --property --subsystem-match=input` zeigt fuer diese Nodes bei `trigger add/change` aber weiter nur `KERNEL`-Events, keine `UDEV`-Events
    - `Xorg` oeffnet weiter kein `/dev/input/event*`
    - `Xorg.55.log` zeigt weiter keine `config/udev: Adding input device ...`-Zeilen
  - damit ist der verbleibende Rest fuer morgen klar:
    - nicht mehr Sunshine
    - nicht mehr Device-Passthrough oder `/dev/input`-Bind-Materialisierung
    - nicht mehr die alten statischen `Mouse0`-/`Keyboard0`-Sektionen
    - sondern der udev->Xorg-Hotplug-Pfad fuer die virtuellen Sunshine-Event-Nodes

### Storage / Labels

- Der Storage-Broker wird aktuell weiter gegen Repartitionierungs- und `mkfs`-Busy-Zustaende gehaertet.
- `partlabel` wird jetzt als Fallback fuer die Anzeige genutzt.
- Ein echtes Filesystem-Label (`LABEL`) erscheint erst dann sauber ueberall, wenn `mkfs` vollstaendig erfolgreich durchgelaufen ist.
- Konkreter Live-Befund fuer die frische 500-GB-Partition:
  - `/dev/sdd1` existiert
  - `PARTLABEL=games` ist gesetzt
  - die Broker-Discovery liefert inzwischen auch `label=games`
  - aber `filesystem=""`, weil `mkfs` noch nicht sauber erfolgreich war
- Wichtig fuer die UI-Einordnung:
  - der fruehere Setup-Wizard konnte nach `Format: Fehler ...` trotzdem noch `Provisioning: Fertig` und `Commander-Freigabe: Aktiv` zeigen
  - das war ein echter Wizard-Logikfehler und ist inzwischen korrigiert
- Die veralteten `gaming-station`-Storage-Assets im Commander wurden bereinigt:
  - `gaming-station-config`
  - `gaming-station-data`
  - dadurch zeigt `Simple > Speicherpfade` nicht mehr diese toten alten Pfade
- `runtime-hardware` hatte zwischenzeitlich noch einen echten Live-Ausfall:
  - `GET /api/runtime-hardware/resources?connector=container` scheiterte an einem kaputten State-Write nach `last_resources.json.tmp`
  - der `Simple`-Wizard zeigte dadurch zeitweise gar keine Hardware mehr
  - der Snapshot-/Cache-Write ist jetzt best effort; der Runtime-Hardware-Service wurde neu deployt und liefert wieder Ressourcen
- Fuer CasaOS gilt parallel:
  - der vom Storage-Broker erzeugte Basis-Servicepfad liegt unter `/data/services/containers`
  - dieser Pfad wird an Commander publiziert
  - zusaetzlich wird jetzt ein CasaOS-sichtbarer Alias unter `/DATA/AppData/TRION/<service_name>` erzeugt
  - fuer den aktuellen Container-Speicher gilt live:
    - `/DATA/AppData/TRION/containers -> /data/services/containers`
  - CasaOS fuehrt im eigenen `local-storage.json` aktuell nur `sdb` und `sdc`, nicht aber `sdd`

---

## Schnelle Kontrolle

```bash
# Aktiven Container finden
docker ps --filter 'name=trion_gaming-station' --format '{{.Names}}'

# Host-Sunshine pruefen
systemctl --user status sunshine-host.service

# Container-Status
docker exec $(docker ps --filter 'name=trion_gaming-station' --format '{{.Names}}' | head -1) supervisorctl status

# Sichtbare Fenster auf Host-Display :0
docker exec -u default $(docker ps --filter 'name=trion_gaming-station' --format '{{.Names}}' | head -1) \
  env DISPLAY=:0 HOME=/home/default wmctrl -lx
```
