# Gaming Station Diagnostic und Fixes — 2026-03-26

Datum: 2026-03-26

Archivstatus: Gestoppt und archiviert am 2026-04-01.
Hinweis: Diese Diagnosekette bleibt nur noch als historische Referenz fuer den eingestellten `gaming-station`-/Gaming-Container-Zweig erhalten.

Status dieser Notiz: Historische Diagnosekette, nicht der alleinige operative Ist-Stand

Heute zuerst lesen:

1. `2026-03-24-gaming-station-container-doc.md`
2. diese Notiz
3. `2026-03-28-gaming-station-host-runtime-discovery-implementationsplan.md`

> Update 2026-03-27:
> Diese Notiz bleibt als Diagnoseprotokoll fuer den alten Zwischenstand relevant, ist aber nicht mehr der alleinige operative Ist-Stand.
> Seit dem Folgetag gilt zusaetzlich:
> - `gaming-station` laeuft wieder auf dem hostnahen `secondary`-/Host-Bridge-Pfad
> - der frische Deploy-Pfad wurde fuer Neuinstallationen gehaertet
> - `runtime-hardware` hat den Input-Passthrough im Legacy-Pfad sauber sichtbar gemacht und gezeigt, dass das Restproblem nicht mehr am reinen Docker-Passthrough lag
> - der Commander hat jetzt einen echten `POST /api/commander/containers/{container_id}/uninstall`-Pfad; `stop` behaelt `gaming-station`, `uninstall` entfernt den gestoppten Container wirklich
> - der aktive Restpunkt liegt aktuell eher im Storage-Broker-Feintuning fuer Repartitionierung, `mkfs`-Busy-Nachlauf und generische Label-/`partlabel`-Anzeige
>
> Update 2026-03-28:
> - im separaten manuellen `gaming-test`-`primary`-Pfad wurden weitere Integrationsfehler belegt
> - der Debian-/`zenity`-Steam-Installer tauchte dort erneut auf
> - Ursache war wieder ein Drift zwischen gespeichertem Blueprint-Dockerfile und aktuellem Generatorstand
> - nach explizitem Store-Refresh wird der Steam-Bootstrap im manuellen `gaming-test`-Pfad jetzt ohne GUI-Prompt akzeptiert
> - zusaetzlich wird das durch `nvidia-xconfig` erzeugte `xorg.conf` dort jetzt sanitiert:
>   - alte `Mouse0`-/`Keyboard0`-Sektionen entfernt
>   - `AutoAddDevices` / `AutoEnableDevices` explizit an
>   - Ignore-Regeln fuer `Touch passthrough`, `Pen passthrough`, `Wireless Controller Touchpad`
> - der `primary`-Pfad faellt ausserdem nicht mehr falsch auf `dumb-udev` zurueck; `/run/udev` wird vor dem alten Image-Check angelegt und echtes `systemd-udevd` laeuft
> - eine spaete eigene udev-Regel setzt fuer `Mouse passthrough*` und `Keyboard passthrough` auf den Event-Nodes jetzt explizit `ID_SEAT=seat0` und `TAG+=seat`
> - der verbleibende Restkandidat im manuellen `primary`-Testpfad sitzt damit jetzt noch enger im udev->Xorg-Hotplug:
>   - auf `event21` / `event22` / `event23` liegen jetzt `seat`-Infos direkt am Event-Node
>   - `udevadm monitor` zeigt fuer diese Nodes bei `trigger add/change` aber weiter nur `KERNEL`, kein `UDEV`
>   - `Xorg` bindet sie weiter nicht
> - spaeter am 2026-03-28 wurde der Deploy-Pfad fuer denselben `gaming-test`-`primary`-Pfad weiter eingegrenzt:
>   - `runtime-hardware` lieferte fuer die gewuenschten Intents sauber `supported=true`
>   - fuer `input` wurde korrekt ein Bind-Mount `/dev/input -> /dev/input` aufgeloest
>   - der echte Startpfad blockierte diesen korrekten Hardware-Bind aber zunaechst wieder an `storage_scope`
>   - Root Cause war `validate_blueprint_mounts(...)`: jeder Bind-Mount wurde wie persistenter Storage behandelt
>   - `/dev/input` fiel dadurch faelschlich unter `storage_scope_violation: mount '/dev/input' is outside scope 'gaming-station'`
>   - der generische Fix sitzt jetzt in `container_commander/storage_scope.py`:
>     - Runtime-/Hardware-Binds fuer systemnahe Namespaces (`/dev`, `/proc`, `/sys`, `/run/udev`, `/run/dbus`, `/run/user`, `/var/run/dbus`, `/tmp/.X11-unix`) werden nicht mehr wie Storage-Binds behandelt
>     - die Ausnahme ist absichtlich eng:
>       - nur Bind-Mounts
>       - nur ohne `asset_id`
>       - nur bei identischem Host- und Container-Pfad
>   - danach lief ein frischer `gaming-test`-Deploy wieder mit
>     - `hardware_resolution_preview.supported=true`
>     - `mount_override_count=1`
>     - `docker inspect ... .Mounts` zeigt real `{"Source":"/dev/input","Destination":"/dev/input","Type":"bind"}`
>     - `HostConfig.Devices` enthaelt `/dev/input` nicht mehr
>     - Host- und Container-Inode fuer `/dev/input` sind jetzt identisch (`142`)
>   - der Input-Transportpfad bis in den Container ist damit fuer neue Deploys repariert; der naechste echte Resttest bleibt wieder der Laufzeitpfad `Sunshine -> virtuelle event21-23 -> Xorg`
> - spaeter am 2026-03-28 wurde die uebergeordnete Produktentscheidung getroffen:
>   - Sunshine im selben Container wie Steam gilt nicht mehr als belastbarer Zielpfad
>   - `gaming-station` soll kuenftig Sunshine auf dem Host **nur noch erkennen und melden**
>   - `gaming-station` soll **nichts** mehr auf dem Host installieren, materialisieren, enablen oder starten
>   - daraus folgt ein neuer Scope:
>     - `host_companion`-Mutation ist fuer `gaming-station` nicht mehr das Zielmodell
>     - benoetigt wird stattdessen ein eigener read-only Host-Runtime-Discovery-Pfad
>   - der dazugehoerige Implementationsplan liegt in:
>     - `2026-03-28-gaming-station-host-runtime-discovery-implementationsplan.md`
> - spaeter am 2026-03-28 nach Umsetzung dieses neuen Scope:
>   - `gaming-station` deployt wieder ueber den read-only Host-Runtime-Discovery-Pfad
>   - der echte Engine-/Host-Helper-Befund erkennt `sunshine-host.service` wieder als aktiv
>   - der frische Test-Deploy lief ohne neue Host-Mutation
>   - die Maus funktioniert in diesem Stand wieder
>   - zunaechst waren Desktop und Steam im Stream noch nicht sichtbar
>   - der neue Restpunkt lag damit nach der Input-Rueckkehr im Desktop-/App-Startpfad des Host-Bridge-Setups
> - spaeter am 2026-03-28 wurde dieser Host-Bridge-Desktop-Pfad weiter eingegrenzt und teilweise repariert:
>   - `desktop` war im `secondary`-Pfad effektiv deaktiviert
>   - ein manueller Runtime-Test zeigte, dass `start-desktop.sh` zuerst in einem `xterm` fuer Flatpak-First-Run-Install hing
>   - ein zweiter Runtime-Test zeigte, dass `startxfce4` danach gegen den bereits laufenden Host-Window-Manager `openbox` kollidierte
>   - der Build-/Generatorpfad fuer `gaming-station` wurde deshalb geaendert:
>     - eigener `start-desktop-host-bridge.sh`
>     - `desktop` autostartet wieder
>     - `/tmp/.desktop-apps-updated` wird im Host-Bridge-Pfad vorab gesetzt
>     - `xfwm4 --replace` uebernimmt den WM-Slot von Host-`openbox`
>     - Steam wartet mit `wait_for_desktop` auf die Session
>   - frischer Live-Deploy `trion_gaming-station_1774703243545_47e308` belegt danach:
>     - `desktop RUNNING`
>     - `steam RUNNING`
>     - `xfce4-panel`, `xfdesktop`, `xfwm4` sichtbar auf `DISPLAY=:0`
>     - nach dem ersten Steam-Update erscheint wieder ein sichtbares Steam-Fenster
>     - dieses Fenster ist aktuell `Sign in to Steam`
>   - damit ist der Desktop-/Window-Manager-Pfad fuer `gaming-station` wieder funktionsfaehig
>   - der neue Rest sitzt jetzt beim Steam-Login-/Account-Zustand

---

## Kontext

Nach einem laengeren Entwicklungs-Zyklus (Codex + Claude parallel) wurde eine vollstaendige Diagnose-Session fuer drei bekannte Gaming-Container-Probleme durchgefuehrt.

Wichtig: Ziel war ausschliesslich belegbare Ursachen — keine Vermutungen, keine "koennte der Grund sein"-Aussagen. Alle Befunde sind direkt aus Logs, API-Tests oder Code belegt.

Wichtig fuer heutige Leser:

- Diese Notiz enthaelt bewusst auch aeltere `primary`-/Container-Sunshine-Befunde.
- Diese alten Befunde bleiben als Diagnosehistorie relevant.
- Sie sind aber nicht mehr das Produktziel von `gaming-station`.

---

## Problem 1: Tote Container lassen sich nicht entfernen

### Fehlerbild

```
internal_error host-helper /v1/remove-paths failed: 404 {"detail": "Not Found"} {HTTP 500}
```

### Ursache

Die Route `/v1/remove-paths` existiert im Source-Code `mcp-servers/storage-host-helper/app.py:462`, aber der deployede `storage-host-helper`-Container war veraltet.

Beweis: Direkter API-Test gegen den laufenden Container:

```
POST /v1/remove-paths → HTTP 404 Not Found
GET  /health          → HTTP 200 OK
```

Der Container war `Up 2 days` und wurde nie neu gebaut, nachdem die Route im Source hinzugefuegt wurde.

### Fix

```bash
docker compose -f <repo-root>/docker-compose.yml build storage-host-helper
docker compose -f <repo-root>/docker-compose.yml up -d storage-host-helper
```

Nach Rebuild:

```
POST /v1/remove-paths (leere Liste) → HTTP 400 Bad Request
```

HTTP 400 ist korrekt — die Route validiert Eingaben. Route ist jetzt aktiv.

### Nebenerkennnis: Container blieb trotz Uninstall gelistet

Auch nach erfolgreichem Uninstall blieb der Container `trion_gaming-station_1774461010784_367d75` gelistet.

Ursache: `engine.py:606`

```python
PRESERVE_ON_STOP_BLUEPRINT_IDS = {"gaming-station"}
```

Der `stop_container()`-Aufruf ohne explizites `remove=True` entfernt gaming-station-Container bewusst nicht. Der Uninstall-Flow ruft `stop_container()` ohne `remove=True` — dadurch bleibt der Docker-Container im `Exited`-Zustand stehen.

Fix fuer diese Session: manuelles `docker rm <container-id>`.

Damals naheliegender Fix: Der Uninstall-Endpunkt sollte den Container explizit entfernen.

Update 2026-03-27:

- Das ist inzwischen umgesetzt.
- Der Commander hat jetzt einen echten `POST /api/commander/containers/{container_id}/uninstall`-Pfad.
- `stop` behaelt `gaming-station`, `uninstall` entfernt den gestoppten Container wirklich.

---

## Problem 2: Maus und Tastatur funktionieren nicht remote

### Fehlerbild

Moonlight verbindet sich, Stream laeuft, aber Maus und Tastatur reagieren nicht.

### Ursache

`Warning: Unrecognized configurable option [qos]` in `/home/default/.cache/log/sunshine.log`

Das generierte `sunshine.conf` enthaelt `qos = disabled`, aber die Sunshine-Version im Container (`2025.924.154138`) kennt diese Option nicht. Der Eintrag wird vollstaendig ignoriert.

Folge: Sunshine versucht bei jedem UDP-Stream-Paket DSCP/QoS-Bits zu setzen. Das schlaegt auf dem Docker-Bridge-Netzwerk mit EACCES fehl, weil der `default`-User (UID 1000) keine `CAP_NET_ADMIN`-Capability hatte:

```
[22:55:05] Warning: sendmsg() failed: 13
[22:55:05] Warning: sendmsg() failed: 13
[22:57:17] Warning: sendmsg() failed: 13
... (beide aufgezeichneten Sessions, mehrfach)
```

### Warum `cap_add=["NET_ADMIN"]` im Blueprint nicht geholfen hat

Das Blueprint hat `cap_add=["NET_ADMIN", "SYS_ADMIN", "SYS_NICE"]` und `privileged=True`. Trotzdem funktionierte es nicht.

Grund: Linux-Capabilities sind per-Prozess, nicht per-Container. Ein Prozess der als UID 1000 (non-root) laeuft, hat Capabilities nur wenn:
- er als root laeuft, ODER
- das ausfuehrbare Binary File-Capabilities via `setcap` gesetzt hat

`cap_add` und `privileged=True` stellen Capabilities im Container-Bounding-Set bereit, aber ein non-root Prozess erbt diese nicht automatisch in seinen Effective-Set.

### Diagnose: Sunshine-Binary ist ein Symlink

```bash
/usr/bin/sunshine -> sunshine-2025.924.154138
```

`setcap` auf einen Symlink wirkt nicht. Linux setzt Capabilities nur auf echte Dateien (ELF-Binaries), nicht auf Symlinks. Der erste Fix-Versuch mit `setcap cap_net_admin+ep /usr/bin/sunshine` im Dockerfile hatte deshalb keinen Effekt.

Korrekte Loesung: `realpath` im Dockerfile verwenden:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends libcap2-bin \
    && rm -rf /var/lib/apt/lists/* \
    && setcap cap_net_admin+ep "$(realpath /usr/bin/sunshine)"
```

Verifizierung nach Deploy:

```
getcap $(realpath /usr/bin/sunshine)
/usr/bin/sunshine-2025.924.154138 cap_net_admin=ep
```

`ep` = effective + permitted. Sunshine kann jetzt DSCP-Bits setzen.

### Nebenerkenntnis: ensure_gaming_station_blueprint() wird beim REST-Deploy nicht aufgerufen

`ensure_gaming_station_blueprint()` wird in `mcp_tools.py:769` aufgerufen — aber nur wenn das Deployment ueber den MCP-Tool-Pfad (`_tool_request_container`) laeuft.

Der REST-API-Endpunkt `/api/commander/containers/deploy` ruft diese Funktion NICHT auf. Das Blueprint in der DB wird nicht aktualisiert. Der Deploy benutzt das gecachte Blueprint aus der DB.

Folge: Code-Aenderungen in `mcp_tools_gaming.py` werden beim naechsten REST-Deploy ignoriert, weil das Blueprint in der DB noch den alten Stand hat.

Workaround (manuell nach Code-Aenderung):

```bash
docker exec jarvis-admin-api python3 -c "
from container_commander.mcp_tools_gaming import ensure_gaming_station_blueprint
ensure_gaming_station_blueprint()
"
```

Langfristiger Fix: Der REST-Deploy-Endpunkt sollte `ensure_gaming_station_blueprint()` fuer bekannte dynamisch generierte Blueprints ebenfalls aufrufen — oder ein generischer "Blueprint-Refresh"-Mechanismus sollte vor jedem Deploy greifen.

### Image-Tag ist content-addressed

`engine.py:248`:

```python
fingerprint = hashlib.sha256(dockerfile.encode("utf-8")).hexdigest()[:12]
return f"trion/{blueprint.id}:{fingerprint}"
```

Das Docker-Image-Tag ist ein SHA256-Hash des Dockerfile-Inhalts. Aendert sich der Dockerfile, aendert sich der Tag, und ein neues Image wird gebaut. Bleibt der Dockerfile gleich (weil die DB nicht aktualisiert wurde), wird das alte gecachte Image weiterverwendet.

### Spaeterer Beleg: derselbe Drift trat erneut im manuellen `gaming-test`-Pfad auf

- Der Generator in `jarvis-admin-api` lieferte bereits einen neueren `gaming_station_primary_dockerfile(...)`-Stand.
- Der gespeicherte `gaming-test`-Blueprint in SQLite lief trotzdem weiter mit einem aelteren Dockerfile-Fingerprint.
- Belegbar war das dadurch, dass im laufenden Container die neuen Patch-Inhalte fehlten:

Publish-Hinweis 2026-04-07: Repo-absolute Host-Pfade wurden in dieser Archivnotiz auf `<repo-root>`-Platzhalter umgestellt.
  - `/usr/games/steam` enthielt weiter den `zenity`-Prompt
  - das generierte `xorg.conf` enthielt weiter die alten statischen `Mouse0`-/`Keyboard0`-Sektionen
- Erst nach explizitem `update_blueprint('gaming-test', {'dockerfile': gaming_station_primary_dockerfile(...)})` wurde ein neuer content-addressed Tag gebaut und gestartet.

---

## Problem 3: PS4 Controller nicht verbunden

### Fehlerbild

Controller wird im Gaming-Container nicht erkannt.

### Ursache

```bash
bluetoothctl info 58:10:31:39:50:06
    Paired: yes
    Bonded: yes
    Trusted: yes
    Connected: no
```

Der Controller ist auf dem Host gepaired, aber zum Zeitpunkt der Diagnose nicht aktiv verbunden. `/dev/input/js0` existiert als veraltete Geraete-Datei aus der letzten aktiven BT-Session.

Das ist kein Code-Problem. Der Controller muss durch Druecken der PS-Taste neu mit dem Host verbunden werden.

Sobald der Host `Connected: yes` zeigt, erbt der Container das Geraet automatisch (Container hat `privileged=True`, sieht alle `/dev/input`-Geraete des Hosts).

---

## Sunshine-Log-Erkenntnisse waehrend der Analyse

### Stream-Sessions aus dem Log

Zwei echte Stream-Sessions wurden geloggt:

```
22:54:59 New streaming session started [active sessions: 1]
22:54:59 CLIENT CONNECTED
22:54:59 Streaming bitrate is 10508000   ← 10.5 Mbps, aktiv
22:56:00 CLIENT DISCONNECTED

22:57:15 New streaming session started [active sessions: 1]
22:57:15 CLIENT CONNECTED
22:57:15 Streaming bitrate is 10508000
22:57:35 CLIENT DISCONNECTED
```

Beide Sessions liefen kurz (1 Minute bzw. 20 Sekunden). Der Stream war grundsaetzlich aktiv.

### global_prep_cmd undo loest Sunshine-Restart aus

Die Sunshine-Config hat:

```json
"global_prep_cmd": [{"do": "/usr/bin/xfce4-minimise-all-windows", "undo": "/usr/bin/sunshine-stop"}]
```

Beim Session-Ende ruft Sunshine `undo` auf, also `/usr/bin/sunshine-stop`. Das schickt SIGINT an Sunshine (exit status 130). supervisord startet Sunshine danach automatisch neu. Das ist by Design, aber es erklaert die mehrfachen Sunshine-Neustarts im supervisord-Log.

### NvFBC und Virtual Desktop

```
Info: Found [1] outputs
Info: Virtual Desktop: 1920x1080
Info: Screencasting with NvFBC
```

`Virtual Desktop` bedeutete in diesem damaligen Stand, dass NvFBC den Xvfb-Display (`DISPLAY=:55`) des Containers erfasste, nicht den physischen Host-Monitor. Das war korrekt fuer den damaligen `MODE=primary`-Zwischenstand, ist aber nicht mehr die aktuelle Zielarchitektur.

---

## Spaeterer Folge-Befund fuer den manuellen `gaming-test`-`primary`-Pfad

Der bis dahin offene Punkt "Docker-/Passthrough oder udev/Xorg?" wurde am 2026-03-28 weiter aufgeloest.

### Belegter Root Cause im Deploy-Pfad

- `runtime-hardware` inventarisierte die relevanten Ressourcen korrekt:
  - `container::input::/dev/input/event3`
  - `container::device::/dev/dri/renderD128`
  - `container::device::/dev/dri/card0`
  - `container::device::/dev/dri/by-path`
  - `container::device::/dev/uinput`
  - `container::device::/dev/vfio/vfio`
  - `container::usb::/dev/bus/usb/007/003`
  - `container::block_device_ref::/dev/sdd1`
- `POST /hardware/plan` lieferte dafuer `supported=true`.
- Die Hardware-Aufloesung im Commander lieferte korrekt:
  - `mount_overrides=[/dev/input -> /dev/input]`
  - `device_overrides` ohne `/dev/input`
- Der echte `start_container()`-Pfad scheiterte danach aber an:

```text
storage_scope_violation: mount '/dev/input' is outside scope 'gaming-station'
```

### Was daran falsch war

`container_commander/storage_scope.py` behandelte jeden Bind-Mount als persistenten Storage-Bind.

Das war fuer normale Host-Pfade unter `/data/...` korrekt, aber fuer Runtime-/Hardware-Binds falsch. Der neue `/dev/input`-Bind war kein persistenter Storage-Pfad, sondern Teil des Hardware-Deploys.

### Generischer Fix

`validate_blueprint_mounts(...)` wurde deshalb dynamisch gehaertet:

- Storage-Scope bleibt fuer normale persistente Bind-Mounts unveraendert strikt.
- Runtime-/Hardware-Binds fuer systemnahe Namespaces werden aus der Storage-Scope-Pruefung herausgenommen.
- Die Ausnahme ist absichtlich eng:
  - nur `type=bind`
  - kein `asset_id`
  - identischer Host- und Container-Pfad
  - nur fuer bekannte Runtime-Namensraeume:
    - `/dev`
    - `/proc`
    - `/sys`
    - `/run/udev`
    - `/run/dbus`
    - `/run/user`
    - `/var/run/dbus`
    - `/tmp/.X11-unix`

### Live-Verifikation nach dem Fix

Ein frischer `gaming-test`-Deploy lief danach mit:

- `hardware_resolution_preview.supported=true`
- `mount_override_count=1`
- `unresolved_resource_ids=[]`

Docker-seitig war danach real belegt:

- `Mounts` enthaelt `/dev/input -> /dev/input` als echten Bind-Mount
- `HostConfig.Devices` enthaelt `/dev/input` nicht mehr
- Host- und Container-Inode fuer `/dev/input` sind jetzt identisch

```text
host      142 /dev/input
container 142 /dev/input
```

Damit ist fuer neue Deploys der eigentliche Input-Transport bis in den Container wieder korrekt. Der verbleibende Laufzeitrest fuer Moonlight/Sunshine liegt damit wieder beim Verhalten von `Xorg` gegenueber den spaeter von Sunshine erzeugten virtuellen Event-Nodes.

Die zusaetzlich geloggten physischen Displays (`DVI-D-0 connected: true`) sind nur die GPU-Output-Auflistung, nicht die Capture-Quelle.

---

## Warum Sunshine-Input-Events nicht im Log erscheinen

Sunshine loggt Input-Events (Maus, Tastatur, Controller) nur auf Debug-Level. Mit `min_log_level = info` tauchen Input-Ereignisse nicht im Log auf. Das bedeutet: fehlende Input-Log-Eintraege sagen nichts darueber aus ob Input funktioniert oder nicht.

Fuer echte Input-Diagnose: `min_log_level = debug` setzen (temporaer, da sehr verbose).

---

## Recap: Was funktioniert, was ist jetzt gefixt

| Bereich | Vorher | Nachher |
|---------|--------|---------|
| Container entfernen | 404 auf `/v1/remove-paths` | storage-host-helper neu gebaut, Route aktiv |
| Sunshine QoS | `sendmsg() failed: 13` wegen EACCES, `qos=disabled` ignoriert | `cap_net_admin=ep` via setcap auf echtem Binary |
| PS4 Controller | Not connected | Host-seitiger BT-Reconnect noetig (kein Code-Problem) |

---

## Offene Punkte

1. **Uninstall entfernt Container nicht**: `stop_container()` ohne `remove=True` laesst Exited-Container stehen bei PRESERVE-Blueprints. Uninstall-Endpunkt sollte `remove=True` uebergeben.

2. **ensure_gaming_station_blueprint() nicht im REST-Deploy-Pfad**: Nach Code-Aenderungen in `mcp_tools_gaming.py` muss manuell via `docker exec jarvis-admin-api` aktualisiert werden. Langfristig sollte der Deploy-Endpunkt das selbst tun.

3. **Input-Verifikation steht noch aus**: Ob Maus/Tastatur nach dem `cap_net_admin`-Fix wirklich funktioniert, muss im naechsten echten Moonlight-Test bestaetigt werden.

4. **qos-Option in Sunshine-Version ungueltig**: Auch wenn `cap_net_admin` jetzt DSCP-Markierung erlaubt, bleibt die `qos`-Option in `sunshine.conf` unbekannt fuer diese Sunshine-Version. Die Warnung erscheint weiter, ist aber jetzt harmlos da DSCP funktioniert. Langfristig: entweder neuere Sunshine-Version mit `qos`-Support oder die Option aus dem generierten Config entfernen.
