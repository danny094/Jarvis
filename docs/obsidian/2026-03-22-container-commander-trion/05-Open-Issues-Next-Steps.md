# Offene Punkte und nächste Schritte

## Aktueller Prioritätswechsel

Stand: 2026-03-27

Der fruehere Prioritaetswechsel ist inzwischen **abgearbeitet**:

- `runtime-hardware` v0 ist live
- `Simple > Neues Blueprint` nutzt den neuen Hardware-Pfad bereits praktisch
- `gaming-station` war dafuer der erste echte Realtest
- `Simple > Neues Blueprint` unterstuetzt inzwischen auch ein eigenes Dockerfile direkt in der Uebersicht

Der aktuelle Fokus liegt jetzt auf **Produktisierung und Härtung der Live-Pfade**:

1. Storage-Broker-Repartitionierung / `mkfs` / Label-Anzeige sauberziehen
2. Commander-/UI-Flows auf echte Nutzerpfade glätten
3. Live-Pfade ohne den frueheren `gaming-station`-Sonderzweig weiter vereinheitlichen

Archivhinweis 2026-04-01:

- Der fruehere `gaming-station`-/Gaming-Container-Zweig ist gestoppt und archiviert.
- Die Detailnotizen dazu liegen gesammelt unter [[Archiv/2026-04-gaming-station/00-Archiv-Index|Archiv/2026-04-gaming-station]].

## Was jetzt gut funktioniert

- Container-Commander ist deutlich stabiler
- Container-Query-Klassentrennung fuer Inventar / Blueprint / Binding ist jetzt
  im Chatpfad sichtbar verankert
- `container_addons` sind jetzt explizit an `query_class` gekoppelt statt nur
  lose an Freitext
- der Output-Contract trennt Runtime-Inventar, Blueprint-Katalog und
  Session-Binding jetzt sichtbar
- lokaler Live-Recheck gegen echtes Ollama + reale Runtime-/Blueprint-Daten
  liefert fuer diese drei Fragetypen jetzt contract-konforme Endantworten
- Gaming-Container ist als echter Testfall nutzbar
- `runtime-hardware` ist als eigener v0-Service live
- StorageBroker und Commander sind näher zusammengerückt
- TRION kann direkt im Containerkontext analysieren
- `trion shell` ist praktisch nutzbar
- container-spezifisches Shellwissen ist vorbereitet
- hostnahes Sunshine + Moonlight funktioniert grundsätzlich
- `gaming-station` bleibt bei normalem Stop erhalten
- `gaming-station` wird bei echtem `uninstall` jetzt wirklich entfernt
- `gaming-station` startet nach `stop -> start` ohne erneuten Steam-Installer weiter
- die laufende `gaming-station`-Generation ist jetzt konsistent mit dem aktuellen Host-Bridge-Blueprint
- Steam-Home ist persistent unter `/data/.../steam-home`
- der Commander-/Quota-Stand wird jetzt gegen den realen Docker-Zustand synchronisiert
- Bind-Mount-Hostpfade unter `/data/...` werden jetzt nativ über `storage-host-helper` vorbereitet
- Big Picture wird nachweislich wieder auf `1920x1080` stabilisiert, wenn das sichtbare Steam-Fenster zurück auf `1280x800` fällt

## Offene Punkte

### Portable Endpoints / Publish-Hygiene

- Neuer Produktisierungsstrang dokumentiert in
  [[2026-04-07-portable-endpoints-und-publish-hygiene]].
- Obsidian-Leak-Audit und Redaktionsstand dokumentiert in
  [[2026-04-07-obsidian-doc-leak-audit]].
- Stand 2026-04-07:
  - zentraler Endpoint-Resolver eingefuehrt
  - feste `172.17.0.1`-Bruecken aus den produktiven Runtime-/Gateway-Pfaden
    entfernt
  - `runtime-hardware`, `admin-api` und `ollama` nutzen jetzt eine portable
    Kandidatenreihenfolge aus:
    - expliziter Env-URL
    - internem Service-Namen
    - dynamischem Gateway
    - `host.docker.internal`
    - Loopback
  - `OLLAMA_BASE` faellt container-aware nicht mehr pauschal auf
    `host.docker.internal` zurueck
  - Obsidian-Notizen auf echte Host-/Pfad-Leaks redigiert
  - getrackte Logs, Memories, Session-Handoffs und `__pycache__`-Artefakte aus
    dem Git-Index entfernt
  - `sanitize_for_publish.sh --check` ist fuer den aktuellen Index jetzt gruen
- Verifiziert ueber:
  - `tests/unit/test_service_endpoint_resolver.py`
  - `tests/unit/test_runtime_hardware_gateway_contract.py`
  - `tests/unit/test_container_commander_hardware_resolution.py`
  - `tests/unit/test_scope4_compute_routing.py`
  - Gesamt: `43 passed`
- Offener Rest:
  - lokale Dev-/Ops-Skripte und einzelne UI-/MCP-Defaults weiter aufraeumen
  - Publish-Hygiene als automatisierten Clean-/Secret-Scan-Workflow verankern
  - tracked Logs/Memory-Artefakte vor einer oeffentlichen Repo-Freigabe
    tatsaechlich ausraeumen; der erste Sanitizer-Check meldet hier schon
    reale Treffer

### Control Authority / Container-Fallback-Drift

- Neuer dokumentierter Live-Befund: `Control Layer: Approved` ist bei Container-Requests noch kein stabiler Endzustand.
- Der konkrete Drift ist in [[2026-04-01-control-authority-drift-approved-fallback-container-requests]] festgehalten.
- Problemkette aktuell:
  - UI rendert nur rohes `approved`
  - Blueprint-/Routing-Gate kann `request_container` spaeter effektiv entwerten
  - Executor codiert Routing oft als technisches `unavailable`
  - Output-Grounding kippt danach in den generischen Tool-/Evidence-Fallback
- Besonders sichtbar wurde das bei:
  - `TRION Home Container starten`
  - `TRION Home Workspace starten`
- Offene Folgearbeit fuer spaeter:
  - reconcilierten Control-Endzustand im UI anzeigen statt nur `Approved/Rejected`
  - Routing-Block semantisch von technischem `unavailable` trennen
  - Output-Grounding fuer Routing-Block von Tech-Failure entkoppeln
  - harten Home-Start/Reuse-Fast-Path fuer `TRION Home` einfuehren statt generischem `request_container`

### Container Query Contract / Output Separation

- Der Container-Contract-Strang fuer
  - `container_inventory`
  - `container_blueprint_catalog`
  - `container_state_binding`
  ist jetzt im Codepfad praktisch nachgezogen.
- Stand 2026-04-07:
  - `home_start` startet gestoppte `trion-home`-Container jetzt wirklich neu
    statt einen gestoppten Altzustand nur als "reuse" zurueckzugeben
  - `home_start` erzeugt jetzt auch im Workspace-/Chat-Pfad ein sauberes
    `container_started`-Event
  - `container_inventory` behaelt die strukturierte `container_list`-Evidence
    jetzt bis in den Output-Fallback; dadurch kippt die sichtbare Endantwort
    nicht mehr faelschlich auf "keine laufenden/gestoppten Container
    verifiziert"
  - verifiziert ueber:
    - `starte bitte den TRION Home Workspace`
    - `welche container hast du, und welcher Container sind an und welche sind aus?`
  - Ergebnis:
    - `trion-home` bleibt im Backend wirklich `running`
    - Runtime-Inventar zeigt sichtbar:
      - laufend: `trion-home`
      - gestoppt: `runtime-hardware`, `filestash`
    - `container_state_binding` faellt bei Modell-Drift jetzt sichtbar sauber
      auf Binding-/Runtime-Fallback zurueck statt unbelegte Zeit- oder
      Profildeutungen anzuzeigen
  - Nachgezogen am 2026-04-07:
    - `ConversationContainerState` ist jetzt persistent ueber
      `jarvis-admin-api`-Restarts hinweg
    - der Commander-Seeding-Pfad schreibt kanonische Docker-Voll-IDs statt
      kurzer Route-IDs
    - live verifiziert ueber
      `POST /api/commander/containers/<short-id>/trion-shell/start`
      plus API-Restart und anschliessendes Reload des Binding-State aus
      `/app/data/conversation_container_state.json`
- Stand 2026-04-06:
  - Query-Klassen werden frueh kanonisiert
  - `_container_query_policy` wird materialisiert
  - Addon-Resolver ist jetzt explizit an `query_class` gekoppelt
  - der Output-Layer erzwingt sichtbare Antwortgerueste fuer Inventory,
    Blueprint und Binding
  - ein container-spezifischer Postcheck/Safe-Fallback faengt lokale
    Modell-Drift sichtbar ab
- Lokal live geprueft gegen:
  - echten Docker-Bestand (`docker ps -a`)
  - lokalen Blueprint-Katalog aus `memory/blueprints.db`
  - lokales Ollama mit `ministral-3:3b`
- Ergebnis:
  - `Welche Container hast du gerade zur Verfuegung?`
    -> laufend vs. gestoppt sauber getrennt
  - `Welche Blueprints gibt es?`
    -> keine unberechtigte Runtime-Aussage mehr als sichtbare Endantwort
  - `Welcher Container ist gerade aktiv?`
    -> kein Diagnose-/Action-Drift mehr in der Endantwort
- Wichtige Praezisierung:
  - das kleine lokale Outputmodell driftet in Rohantworten teils weiter
  - entscheidend ist jetzt, dass diese Drift fuer den User nicht mehr sichtbar
    bleibt, weil der Container-Contract sie auf einen sauberen
    Contract-Fallback zurueckzieht
- Offener Rest:
  - `container_request`-/Home-Start-/Routing-Drift bleibt separater Folgestrang
  - breiterer End-to-End-Recheck ueber komplette Runtime-Toolwrapper bleibt
    spaeter weiter sinnvoll

### Storage Broker / Labels / Speicherpfade

- Die aktuelle Fehlerkette ist jetzt klar getrennt:
  - `parted` hat auf `/dev/sdd` die Partition `/dev/sdd1` erfolgreich angelegt
  - `mkfs` auf `/dev/sdd1` ist danach weiterhin fehlgeschlagen
  - dadurch ist `sdd1` aktuell im Teilzustand:
    - `PARTLABEL=games`
    - `LABEL=games`
    - aber noch `filesystem=""`
- Das erklaert den Live-Befund:
  - `/dev/sdd1` bleibt nach Reload sichtbar
  - es wurde nicht "etwas anderes" formatiert
  - das Filesystem wurde bisher schlicht noch nicht erfolgreich geschrieben
- Der Storage-Broker-Setup-Wizard hatte dabei einen echten Logikfehler:
  - `Format: Fehler ...` wurde nur als Text gesammelt
  - `Provisioning` und `Commander-Freigabe` liefen trotzdem weiter
  - dieser Pfad ist jetzt gefixt; ein Formatfehler bricht den Setup-Apply ab
- Die Datentraeger-UI hatte ausserdem eine inkonsistente Zielwahl:
  - direkte Aktionen verlangten bislang bei Disks mit Partitionen eine explizit ausgewaehlte Partition
  - der Setup-Wizard nahm bei genau einer brauchbaren Partition dagegen automatisch `/dev/sdd1`
  - auch dieser Unterschied ist jetzt geglaettet
- Die Label-Discovery wurde weiter gehaertet:
  - Storage-Broker nutzt jetzt nicht nur `lsblk LABEL`
  - sondern zusaetzlich `PARTLABEL`, `/dev/disk/by-partlabel` und `blkid`
  - dadurch erscheinen z. B. `games` und `Basic data partition` jetzt wieder konsistenter im Broker
- Der `Simple`-Wizard zeigte veraltete `Speicherpfade`, weil diese nicht aus der Live-Diskliste kamen, sondern aus publizierten Commander-Storage-Assets
  - dort lagen noch alte `gaming-station-config`- und `gaming-station-data`-Eintraege
  - diese toten Assets wurden inzwischen live entfernt
  - aktuell bleibt dort nur noch `sb-managed-services-containers`
- Ein zusaetzlicher Livefehler sass zwischenzeitlich im `runtime-hardware`-Service:
  - `GET /api/runtime-hardware/resources?connector=container` lief auf `500`
  - Ursache war nicht die Discovery, sondern ein OSError beim Schreiben von `last_resources.json.tmp`
  - dadurch zeigte `Simple > Neues Blueprint` zeitweise gar keine Geraete mehr
  - der Snapshot-/Cache-Write ist jetzt best effort; der Service wurde neu deployt und liefert wieder `200 OK`
- Fuer CasaOS ist der aktuelle Befund ebenfalls klarer:
  - der Storage-Broker legt bei `Container-Speicher` den Hostpfad `/data/services/containers` an
  - dieser Pfad wird an Commander publiziert, aber im Broker-/Commander-Code derzeit nicht zusaetzlich an CasaOS registriert
  - CasaOS fuehrt in `/var/lib/casaos/db/local-storage.db` aktuell nur `o_disk`, `o_merge`, `o_merge_disk`
  - die CasaOS-Livecache-Datei `local-storage.json` enthaelt derzeit nur `sdb` und `sdc`, aber nicht `sdd`
  - parallel sieht der Storage-Broker `sdd` und `sdd1` weiterhin ganz normal
- erster Praxis-Fix dafuer ist jetzt live:
  - `storage_create_service_dir(...)` legt fuer managed Servicepfade zusaetzlich einen CasaOS-sichtbaren Alias unter `/DATA/AppData/TRION/<service_name>` an
  - fuer den bestehenden Container-Speicher wurde live angelegt:
    - `/DATA/AppData/TRION/containers -> /data/services/containers`
- Offener Rest fuer diesen Block:
  - `mkfs` auf `/dev/sdd1` weiter endgueltig stabilisieren
  - danach echten Filesystem-Typ und `LABEL` auf dem Device pruefen
  - entscheiden, ob Broker-Servicepfade explizit in CasaOS sichtbar gemacht werden sollen oder bewusst Commander-only bleiben

### Sunshine / Gaming Runtime

- Der eigentliche Streaming-Pfad läuft jetzt hostnah statt im Container
- Sunshine-WebUI, Pairing und Stream funktionieren
- `HEVC` wurde bereits erfolgreich im Log beobachtet, bleibt aber weiterhin etwas, das je Session sauber mit dem Client ausgehandelt werden muss
- noVNC bleibt eher Debug-/Installationspfad als Gaming-Hauptweg
- Audio-/Input-Fehler sind im aktuellen Sunshine-Log nicht auffällig
- Ein separater `gaming-test`-Deploy mit eigenem Dockerfile hat einen echten Integrationsfehler sichtbar gemacht:
  - der fruehere Abort `mount: /proc: permission denied` war kein Storage-Broker-Fehler
  - Ursache war der Flatpak-Init-Schritt im Base-Image `josh5/steam-headless`
  - der abgeleitete Dockerfile-Pfad patched `/etc/cont-init.d/80-configure_flatpak.sh` jetzt so, dass dieser Schritt in unprivilegierten Containern nicht mehr den ganzen Start abbricht
- derselbe Testpfad hatte danach noch zwei weitere harte Integrationsfehler:
  - der Debian-/`zenity`-Steam-Installer tauchte im manuellen `primary`-Pfad erneut auf
  - Ursache war wieder ein Drift zwischen aktuellem Generatorstand und gespeichertem Blueprint-Dockerfile im Store
  - nach explizitem Store-Refresh ist der Steam-Bootstrap im manuellen `gaming-test`-Pfad jetzt promptfrei
  - das von `nvidia-xconfig` erzeugte `xorg.conf` enthielt dort zusaetzlich wieder alte statische `Mouse0`-/`Keyboard0`-Sektionen
  - der generierte `primary`-Pfad sanitiert `xorg.conf` jetzt nachtraeglich:
    - statische Input-Sektionen raus
    - `AutoAddDevices` / `AutoEnableDevices` an
    - Ignore-Regeln fuer `Touch passthrough`, `Pen passthrough`, `Wireless Controller Touchpad`
- derselbe Testpfad zeigt jetzt sauberer die verbleibende zweite Baustelle:
  - `block_device_ref /dev/sdd1` wird bei explizitem Deploy-Opt-in real als Docker-Device durchgereicht
  - mehrere alte nicht-Block-Hardware-Intents (`input`, `usb`, `device`) liefen im spaeteren Deploy dagegen auf `resource_not_found`
  - der verbleibende Rest sitzt damit jetzt im nicht-Block-Resolve ueber spaeteren Deploy-Zeitpunkt und im Live-Input-/Xorg-Hotplug, nicht mehr im Storage-Broker, im `/proc`-Mount-Fail oder im Debian-Steam-Installer
  - zusaetzlich wurde der falsche `dumb-udev`-Fallback im `primary`-Pfad beseitigt:
    - `/run/udev` und `/run/udev/data` werden vor dem alten Image-Check angelegt
    - der Live-Container nutzt damit echtes `systemd-udevd`
  - fuer die Sunshine-Event-Nodes wurde danach noch eine explizite udev-Regel ergaenzt:
    - `Mouse passthrough`
    - `Mouse passthrough (absolute)`
    - `Keyboard passthrough`
    - auf `event21` / `event22` / `event23` liegen damit jetzt `ID_SEAT=seat0` und `G:seat` direkt auf dem Event-Node
  - trotz dieses Fixes bleibt der letzte Rest offen:
    - `udevadm monitor --kernel --udev --property --subsystem-match=input` zeigt bei `trigger add/change` fuer `event21` / `event22` / `event23` weiter nur `KERNEL`, kein `UDEV`
    - `Xorg` loggt weiter keine `config/udev: Adding input device ...`-Zeilen
    - `Xorg` oeffnet weiter kein `/dev/input/event*`
    - morgen ist damit gezielt der udev->Xorg-Hotplug-Pfad dran, nicht mehr Sunshine oder Device-Passthrough
- Host-Input funktioniert inzwischen auch praktisch fuer einen PS4-Controller:
  - Host-Pairing erfolgreich
  - Container erbt `js0` und die zugehoerigen `event*`
  - bei HDMI-TV + Moonlight-Reconnect gibt es aber noch einen Host-Xorg-/libinput-Crashpfad ueber `Touch passthrough` / `Pen passthrough`

### Gaming Station Runtime (gestoppt und archiviert)

- Dieser Abschnitt bleibt nur noch als historische Referenz erhalten.
- Der zugehoerige Arbeitszweig ist seit 2026-04-01 gestoppt und archiviert.

- Der frühere Generations-Mismatch zwischen altem `primary`-Container und neuem Host-Bridge-Blueprint ist bereinigt
- Dockerfile-basierte `gaming-station`-Images nutzen jetzt content-basierte Tags statt nur `latest`
- Der frühere stale Commander-/HTTP-Quota-Zustand wurde durch Docker-State-Sync deutlich entschärft
- Mount-Precreate für Host-Bind-Pfade unter `/data` läuft jetzt host-aware über `storage-host-helper`
- Big-Picture-Fullscreen ist deutlich robuster, sollte aber bei weiteren echten Neustarts und Reconnects weiter beobachtet werden
- Host-Bridge-Container wie `gaming-station` liefern im Container-Detail jetzt wieder sinnvolle Zugänge, obwohl der Container selbst keine Docker-Ports publiziert
- dafür werden Host-Companion-`access_links` synthetisch in `ports`/`connection` des Detail-Response ergänzt
- der GitHub-/Marketplace-basierte `install -> deploy`-Pfad funktioniert jetzt praktisch ebenfalls
- der letzte Fullscreen-Fehler lag an einem fehlenden Window Manager in der Host-X-Session, nicht mehr am Container selbst
- hostseitig wurde `openbox` ergänzt; damit erscheint `Steam Big Picture Mode` wieder als echtes `1920x1080`-Fenster
- der verbleibende Paket-/Installer-Restpunkt ist jetzt vor allem:
  - `openbox` als deklarierte Host-Abhaengigkeit mitzubringen, statt es nur lokal per `apt` nachzuinstallieren
- beim Spieltest mit `7 Days to Die` zeigte sich noch ein Laufzeitrest:
  - Steam kann im Launchpfad bei `ProcessingShaderCache` hängen
  - der eigentliche Game-Binary startet dagegen grundsätzlich
  - der alte aggressive Big-Picture-Helper konnte sich dabei erneut in den Vordergrund drängen und wurde deshalb lokal auf einen passiven Modus entschärft
  - EOS-/Save-Userdata unter `/home/default/.local/share/7DaysToDie` war zeitweise `root:root`; Live-Fix per `chown`, Dauerfix jetzt als geplanter persistenter `userdata`-Mount im Core
  - der Container lief zuvor mit zu wenig RAM; der laufende Stand wurde live auf `16g` angehoben
  - spaeter wurde auch das CPU-Limit auf `6.0` angehoben
  - ein frischer `stop/remove -> deploy`-Test mit dem neuen Stand lief erfolgreich durch
  - im Unity-`Player.log` meldete `7 Days to Die` danach intern knapp `59-60 FPS`
  - der verbleibende Performance-Eindruck wirkt damit eher wie Streaming-/Host-Xorg-/Timing-Reibung als wie ein kaputter Game-Container

### Marketplace / Composite Addon

- `gaming-station` ist jetzt als optionales `composite_addon` vorbereitet
- Bundle-Support kann `Blueprint + Host Companion + Paketdateien` gemeinsam tragen
- Bundle-Support kann inzwischen auch `container_addons/...` gemeinsam tragen
- Host-Companion-Dateien können über `storage-host-helper` nativ auf dem Host materialisiert werden
- ein `binary_bootstrap` für `sunshine` ist vorbereitet
- ein sicherer `gaming-station-shadow`-Pfad wurde live verifiziert, ohne den laufenden Host-Service zu beschädigen
- ein kontrollierter lokaler Marketplace-Install gegen einen temporären Shadow-Bundle-Pfad wurde erfolgreich durchgeführt
- ein echter GitHub-basierter Installflow läuft jetzt ebenfalls durch:
  - `sync_remote_catalog(...)`
  - `install_catalog_blueprint("gaming-station")`
  - Bundle-Import
  - Paket-Install
  - Runtime-`container_addons`-Install
- dabei wurde ein echter Export-/Import-Roundtrip-Bug gefunden und behoben:
  - `export_bundle()` muss Blueprint-Daten im JSON-Modus serialisieren, sonst landen Python-Tags wie `NetworkMode` im YAML
- Bundle-Addons werden jetzt nicht mehr in den read-only Codepfad unter `/app/intelligence_modules/...` geschrieben
- stattdessen landen sie in einem Runtime-Overlay unter `/app/data/marketplace/container_addons`
- der Addon-Loader berücksichtigt dieses Overlay zusätzlich zum Repo-Stand
- der eigentliche End-to-End-Pfad `deploy -> host companion check/install -> postchecks -> start` ist jetzt der nächste größere Test offen
- dieser End-to-End-Pfad wurde inzwischen erfolgreich bis zum laufenden GitHub-deployten Container durchgezogen
- der Installer versteht jetzt zusätzlich additive Catalog-Felder wie:
  - `package_url`
  - `has_host_companion`
  - `supports_trion_addons`
- der aktive Installpfad bleibt aber bewusst `bundle_url`-zentriert
- der lokale Host-Companion-Lifecycle ist jetzt im Kern vollständig:
  - `host_packages.apt`
  - `binary_bootstrap`
  - `postchecks`
  - `check / repair / uninstall`
- diese Aktionen sind inzwischen auch ueber Commander-API und Commander-Frontend erreichbar
- eine kleine Store-Ecke bleibt dabei sichtbar:
  - `delete_blueprint()` ist Soft-Delete
  - Wiederverwendung derselben Blueprint-ID kann deshalb in SQLite an `UNIQUE` scheitern, wenn man Test-IDs nicht variiert

### TRION Shell

- GUI-Interaktionen sind besser, aber noch nicht perfekt
- echte autonome Mehrschritt-Ausführung wurde bewusst noch nicht aktiviert
- Risk-Gates sind aktuell eher leichtgewichtig als tief integriert
- der frühere WebSocket-Race im Shell-Attach-Pfad wurde entschärft:
  - `attach`/`stdin` werden nicht mehr still verworfen, wenn der Socket noch nicht `OPEN` ist
  - beim Reconnect wird der aktuell angehängte Container automatisch erneut attached

### Addons

- `addon_docs` werden inzwischen im Commander-UI angezeigt
- das Addon-System ist vorbereitet, aber noch jung
- mehr Containerprofile würden den praktischen Nutzen schnell erhöhen

### Orchestrator-Architektur / Entflechtung

- Neuer Architekturpfad dokumentiert in
  [[2026-04-07-orchestrator-architektur-refactor-plan]].
- Stand 2026-04-07:
  - `core/orchestrator.py` ist inzwischen ein echter Wartungsblocker
  - der Refactor soll **kein** Big-Bang-Rewrite sein, sondern eine
    kontrollierte Extraktion in fachliche Module
  - zuerst sollen reine oder fast-pure Entscheidungsbloecke herausgezogen
    werden, nicht sofort der gesamte `process_request(...)`-Pfad
- bevorzugter erster Schnitt:
  - Domain-/Container-Policy
  - Tool-Shaping fuer `request_container` / `home_start` / Binding
  - Grounding-/Repair-nahe Entscheidungslogik nur dort, wo sie klar abgrenzbar
    ist
- explizite Leitplanken:
  - keine Produktfeatures mit dem Refactor vermischen
  - vor jedem Schnitt Pinning-Regressionen fuer Container-/Control-/Output-
    Pfade sichern

## Empfohlene nächste Schritte

1. Storage-Broker-Repartitionierung und `mkfs` weiter haerten
   - `udev`-/Kernel-Nachlauf beim Repartitionieren
   - `mkfs`-Retry/Busy-State
   - generische `LABEL`/`PARTLABEL`-Anzeige konsistent machen
   - CasaOS gegen den aktuellen Storage-Zustand gegenpruefen:
     - `GET /v2/local_storage/merge` liefert weiter `503`, weil `EnableMergerFS=false`
     - CasaOS fuehrt aktuell `sdb` und `sdc`, aber nicht `sdd`
     - Broker-Servicepfade wie `/data/services/containers` erscheinen dort aktuell nicht automatisch
2. Historischen `gaming-station`-Stand nur noch archiviert referenzieren
   - keine weitere operative Arbeit in diesem Dokument, nur noch Verweise auf das Archiv
   - Host-Companion/AppImage-Pfad weiter beobachten
3. `runtime-hardware`-Folgepolish weiterfuehren
   - sprechende Storage-/Block-Device-Namen
   - weitere UI-/Preset-Haertung
   - nicht-Block-Hardware-Intents (`input`/`usb`/`device`) gegen spaetere Re-Deploys stabilisieren
   - pruefen, ob die `Simple`-Auswahl dort staerkere stabile Schluessel statt roher Hostknoten braucht
4. den neuesten GitHub-/Marketplace-Paketstand erneut importieren, damit Host-Companion- und Paket-Haertungen auch im Runtime-Paketstore liegen
5. HEVC-/Bitrate-/Client-Abstimmung für Moonlight weiter feinjustieren
   - insbesondere keine unnötig hohen `150 Mbps` bei `1080p`
   - `Frame Pacing` nur mit Bedacht
6. weitere echte Restart-/Reconnect-Zyklen gegen Big-Picture-Fullscreen prüfen
7. weitere Containerprofile ergänzen, z. B. Datenbank-, MCP-, Web- und Service-Container
8. Shell-Policy weiter schärfen, vor allem für GUI- und Write-Aktionen
9. spaeter Mikro-Loops und erst danach echte Shell-Autonomie nachziehen
10. bei Bedarf Blueprint-seitige Addon-Registrierung ergänzen
11. Commander-UI optional klarer anzeigen lassen, wenn ein Service `stopped and preserved` ist
12. den trägen Tabwechsel / verspätete Panel-Updates im Commander gezielt untersuchen
13. `7 Days to Die`/Steam-Launchpfad härten:
   - Shader-Precache für problematische Testsituationen entschärfen
   - prüfen, warum `steam://open/bigpicture` während eines laufenden Spiels erneut auftaucht
   - `nofile`-Limit für die Runtime anheben
14. Sunshine-/Host-Xorg-Pfad weiter glätten:
   - wiederkehrende `libinput`-/`InitPointerDeviceStruct()`-Meldungen in der Host-Xorg-Session beobachten
   - prüfen, ob dort noch Input-/Frametime-Reibung fuer Moonlight entsteht
   - insbesondere im Auge behalten, dass Host-Service-Neustarts gleichzeitig Stream und lokales TV-Bild wegziehen koennen
   - den vorbereiteten Xorg-Ignore-Fix fuer `Touch passthrough`, `Pen passthrough` und `Wireless Controller Touchpad` auf dem Host materialisieren und gegen HDMI+Moonlight-Reconnect testen
   - nach Crash/Restart den Moonlight-Clientzustand mitpruefen; `RTSP handshake failed: 60` trat trotz `ufw inactive` und laufendem `sunshine-host.service` auf und wirkt derzeit eher wie ein staler Session-/Pairing-Zustand
15. manuellen `gaming-test`-`primary`-Pfad zu Ende haerten:
   - verifizieren, dass der neue promptfreie Steam-Bootstrap stabil bleibt
   - verifizieren, dass das sanitisierte `xorg.conf` jetzt auch im Live-Inputtest sauber mit Sunshine-Hotplug arbeitet
   - den noch offenen `resource_not_found`-Resolver-Block fuer nicht-Block-Intents getrennt vom Xorg-Thema weiter verfolgen
16. neuen `userdata`-Mount bei nächstem Recreate/Neu-Deploy praktisch verifizieren:
   - `/data/services/gaming-station/data/userdata -> /home/default/.local/share`
   - EOS-/Save-Dateien müssen danach ohne manuellen `chown` sauber entstehen
17. Architekturpfad fuer `core/orchestrator.py` starten
   - zuerst kurzer Audit der Funktionscluster
   - dann erster Extraktionsschnitt fuer Domain-/Container-Policy
   - erst spaeter stateful Streaming-/Sync-/Lifecycle-Pfade anfassen

## Mögliche spätere Ausbaustufen

- eigener `shell control model`-Schalter
- user-erweiterbare Addon-Sammlungen pro Blueprint
- stärkere Recovery-/Verification-Strategien
- feinere Storage-/Commander-/TRION-Integration auf Asset-Ebene
