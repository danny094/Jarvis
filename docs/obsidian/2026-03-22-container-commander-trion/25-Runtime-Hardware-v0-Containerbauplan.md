# Runtime Hardware v0 Containerbauplan

Erstellt am: 2026-03-26

Bezug:

- [[23-Runtime-Hardware-Modul-Implementationsplan]]
- [[24-Runtime-Hardware-v0-Installationsvertrag]]

## Zweck dieser Notiz

Diese Notiz beschreibt den konkreten **Bauplan fuer den ersten realen v0-Container** `jarvis-runtime-hardware`.

Hier geht es nicht mehr um Architektur-Grundsatzfragen, sondern um die praktische Reihenfolge fuer den ersten umsetzbaren Schnitt:

- welche Repo-Bereiche angelegt werden
- welche Dateien in v0 entstehen
- wie Paket, Blueprint und Service zusammenspielen
- welche Teile zuerst echt funktionieren muessen

Wichtig:

- Fokus liegt voll auf `runtime-hardware`
- der `gaming-station`-Kontext ist hier bewusst kein eigener Arbeitspfad mehr
- `gaming-station` bleibt spaeter nur ein moeglicher Realtest, nicht der Treiber dieser Umsetzung

## Statusstand nach dem ersten V0-Schnitt

Stand: 2026-03-27

Bereits umgesetzt:

- `adapters/runtime-hardware/Dockerfile`
- `adapters/runtime-hardware/requirements.txt`
- `adapters/runtime-hardware/main.py`
- `adapters/runtime-hardware/runtime_hardware/api.py`
- `adapters/runtime-hardware/runtime_hardware/models.py`
- `adapters/runtime-hardware/runtime_hardware/planner.py`
- `adapters/runtime-hardware/runtime_hardware/store.py`
- `adapters/runtime-hardware/runtime_hardware/connectors/base.py`
- `adapters/runtime-hardware/runtime_hardware/connectors/container_connector.py`
- `marketplace/packages/runtime-hardware/package.json`
- `marketplace/packages/runtime-hardware/README.md`
- `container_commander/runtime_hardware_blueprint.py`

Zusatzintegration bereits erledigt:

- `adapters/admin-api/Dockerfile` kopiert die neuen Servicequellen ins Admin-API-Image
- `adapters/admin-api/main.py` seeded beim Startup den Blueprint `runtime-hardware`
- `container_commander/blueprint_store.py` behandelt `runtime-hardware` als offiziellen Blueprint
- `adapters/admin-api/runtime_hardware_routes.py` stellt den allgemeinen Gateway-Pfad bereit
- `adapters/admin-api/commander_api/hardware.py` stellt den Blueprint-Hardware-Pfad bereit
- `container_commander/models.py` und `container_commander/blueprint_store.py` persistieren `hardware_intents`
- `container_commander/hardware_resolution.py` uebernimmt die kontrollierte Uebersetzung von `hardware_intents` in spaetere Runtime-Aufloesungen
- `container_commander/engine.py` nutzt diese Aufloesung jetzt bereits fuer klare `device`-/`input`-/`usb`-Faelle im Deploy-Pfad
- `runtime-hardware` zieht jetzt zusaetzlich Storage-Broker-Disks als `block_device_ref` und veroeffentlichte Commander-Assets als `mount_ref`
- `container_commander/engine.py` materialisiert `mount_ref` inzwischen in echte `mount_overrides`, wenn ein expliziter Zielpfad gesetzt ist
- `mount_ref` ist inzwischen gegen reservierte Container-Zielpfade und Asset-Policies gehaertet
- `block_device_ref` bleibt Review-Objekt und wird weiter nicht blind materialisiert
- die Policy-/Resolution-Logik dafuer liegt jetzt separat in `container_commander/hardware_block_resolution.py`
- die Apply-Vorbereitung und der spaetere Kandidatenplan liegen jetzt separat in:
  - `container_commander/hardware_block_apply.py`
  - `container_commander/hardware_block_apply_plan.py`
- der erste Container-spezifische Adapter liegt jetzt separat in:
  - `container_commander/hardware_block_container_adapter.py`
- die Storage-Discovery dafuer liegt jetzt separat in `adapters/runtime-hardware/runtime_hardware/connectors/container_storage_discovery.py`
- der `runtime-hardware`-Plan transportiert dafuer jetzt Broker-/Ressourcen-Metadaten bis in den Commander-Resolver
- live verifiziert: ein System-Datentraeger wie `container::block_device_ref::/dev/sda` wird im Resolve-Pfad jetzt hart blockiert statt nur allgemein gewarnt
- zusaetzlich abgesichert: der `runtime-hardware`-Blueprint embedet die neue Discovery-Datei jetzt explizit mit, damit der Live-Container nicht vom Repo-Stand abweicht
- live verifiziert: `resolve` liefert jetzt auch `block_apply_previews`; echte `block_apply_candidates` entstehen nur fuer erlaubte Kandidaten und bleiben derzeit absichtlich deaktiviert
- `block_apply_previews` sind jetzt leicht runtime-neutraler:
  - `target_runtime`
  - `target_runtime_path`
  - `candidate_runtime_binding`
  - container-spezifische Mapping-Details nur noch unter `runtime_parameters.container`
- `block_apply_container_plans` existieren jetzt als eigener, weiter deaktivierter Adapter-Pfad
- `block_apply_engine_handoffs` existieren jetzt als eigener, weiter deaktivierter Engine-Handover-Pfad
- expliziter Engine-Opt-in ist jetzt vorhanden:
  - `container_commander/hardware_block_engine_opt_in.py`
  - `start_container(..., block_apply_handoff_resource_ids=[...])`
  - Standard bleibt aus
  - kein Auto-Apply
- Read-/Preview-Pfad ist jetzt sichtbar:
  - `hardware_preview`
  - `resolution_preview`
  - `block_apply_handoff_resource_ids_hint`
  - `engine_opt_in_available`
- der Deploy-Response enthaelt jetzt zusaetzlich:
  - `hardware_deploy.block_apply_handoff_resource_ids_requested`
  - `hardware_deploy.block_apply_handoff_resource_ids_applied`
  - `hardware_deploy.hardware_resolution_preview`
- der Deploy-Resolver wurde danach noch operativ stabilisiert:
  - `container_commander/hardware_resolution.py` nutzt im echten `admin-api`-/Commander-Prozess jetzt lokal eingebettete `runtime-hardware`-Module bevorzugt fuer Deploy-Resolution
  - der alte HTTP-Pfad zu `runtime-hardware` bleibt als allgemeiner Gateway-/Service-Pfad erhalten, ist aber nicht mehr kritisch fuer den eigentlichen Container-Deploy
  - Storage-nahe Metadaten bleiben dabei sauber:
    - Disks weiter ueber `storage-broker`
    - Storage-Assets lokal ueber `container_commander.storage_assets`
- erster Frontend-Schnitt ist jetzt real vorhanden:
  - `adapters/Jarvis/js/apps/terminal/blueprint-simple.js`
  - `adapters/Jarvis/js/apps/terminal/blueprint-editor.js`
  - `adapters/Jarvis/js/apps/terminal/preflight.js`
- der `Simple`-Wizard liest verfuegbare Ressourcen ueber `GET /api/runtime-hardware/resources?connector=container`
- der `Simple`-Wizard speichert ausgewaehlte Hardware jetzt als `hardware_intents`
  - nicht mehr als rohe `devices`
- der `Simple`-Wizard hat jetzt im Overview-Pfad zusaetzlich ein direktes `Dockerfile`-Feld
- fuer Storage-Hardware werden dort jetzt strukturierte Modi mitgegeben:
  - `block_device_ref` -> bei `managed_rw` direkt `policy.mode=rw`
  - `mount_ref` -> uebernimmt vorhandene Broker-/Source-Modi als `policy.mode`
- `input` ist jetzt als eigene Hardware-Kategorie im Wizard sichtbar
- der bisherige Editor-Pfad ist jetzt bewusst getrennt:
  - `Hardware Preview` = read-only Vorschau
  - `Raw Runtime` = direkter Expertenpfad fuer manuelle `devices`
- der Deploy-Dialog nutzt den echten Runtime-Hardware-Pfad jetzt ebenfalls:
  - opt-in-faehige `block_apply_handoff_resource_ids`
  - sichtbare Rueckmeldung `requested` vs `applied`
- die Frontend-Benennung ist jetzt vereinheitlicht ueber:
  - `adapters/Jarvis/js/apps/terminal/runtime-hardware-ui.js`
  - dieselbe Anzeige fuer Wizard, Deploy-Dialog und read-only Preview
  - Primaerlabel jetzt bevorzugt aus `label` / `vendor` / `product`
  - `host_path` nur noch als technische Sekundaerinfo
- der Editor zeigt fuer neue Blueprints jetzt einen ehrlichen Hinweis:
  - Hardware-Vorschau erst nach dem ersten Speichern verfuegbar
- backendseitig wurde die Input-Label-Ermittlung zusaetzlich gehaertet:
  - `container_connector.py` liest fuer `input` jetzt Sysfs-Namen aus `/sys/class/input/<event>/device/name`
  - dadurch liefert `GET /api/runtime-hardware/resources?connector=container` jetzt nicht mehr nur rohe `event*`-Eintraege
- zusaetzliche Anzeige-/Filter-Haertung fuer `Simple` ist inzwischen umgesetzt:
  - `adapters/runtime-hardware/runtime_hardware/connectors/container_display.py` bereitet sprechende `display_*`-Metadaten vor
  - Input-Ressourcen werden logisch gruppiert
    - Maus-Varianten erscheinen jetzt als ein Eintrag `Maus`
  - technische Audio-/Bus-Eintraege werden in `Simple` verborgen
    - u. a. `HD-Audio`, `Video Bus`, `Monitor-Audio`
  - USB-Ressourcen zeigen bevorzugt Hersteller-/Produktnamen und Rollen
    - u. a. `Bluetooth`, `Speicher`, `Controller`, `Hub`
  - Root-Hubs werden in `Simple` verborgen
  - `mount_ref` zeigt jetzt Groesseninfo aus dem zugeordneten Storage-Broker-Datentraeger
  - `mount_ref` bleibt dabei bewusst asset-basiert:
    - Quelle sind publizierte Commander-Storage-Assets
    - nicht die rohe Live-Diskliste
  - dadurch wurde ein echter Produktfehler sichtbar:
    - alte publizierte Assets konnten im `Simple`-Wizard weiter als `Speicherpfade` auftauchen
    - obwohl die Host-Pfade bereits nicht mehr existierten
  - die alten `gaming-station`-Assets wurden deshalb live entfernt
  - `block_device_ref` blendet in `Simple` kleine Partitionen unter `1 GB` aus
- Gleichzeitig wurde die Storage-Broker-Discovery fuer Labels nachgeschaerft:
  - `PARTLABEL`, `/dev/disk/by-partlabel` und `blkid` werden jetzt als Fallback genutzt
  - dadurch erscheinen z. B. `games` oder `Basic data partition` wieder sauberer im Discovery-Pfad
- Wichtige Live-Einordnung fuer die neue 500-GB-Partition:
  - `/dev/sdd1` kann nach dem Partitionieren bereits sichtbar sein
  - obwohl `mkfs` noch nicht erfolgreich war
  - dann gilt operativ:
    - Partition vorhanden
    - Label/Partlabel sichtbar
    - aber `filesystem=""`
- live verifiziert: bei einem Whole-Disk-Review-Fall entstehen weiterhin keine `block_apply_candidates` und keine `block_apply_container_plans`
- live verifiziert: bei der erlaubten Partition `container::block_device_ref::/dev/sdd1` entstehen jetzt
  - `block_apply_candidate`
  - `block_apply_container_plan`
  - `block_apply_engine_handoff`
  - mit Binding `/dev/sdd1:/dev/game-disk`
  - weiter deaktiviert, weiter ohne Auto-Apply
- zusaetzlicher UI-Haertungsschritt live:
  - der Deploy-Dialog waehlt solche `block_apply_handoff_resource_ids` fuer `simple-wizard`-Auswahlen jetzt standardmaessig vor
  - damit wird ein vorher im Wizard bewusst gewaehltetes `managed_rw`-Block-Device im normalen UI-Pfad automatisch bis zum Commander-Opt-in mitgenommen
- parallel wurde ein separater Dockerfile-Testpfad sichtbar:
  - ein frueher `mount: /proc: permission denied` kam aus `josh5/steam-headless` (`80-configure_flatpak.sh`) und nicht aus dem Storage-Broker
  - der abgeleitete Gaming-Dockerfile-Pfad patched diesen Flatpak-Init jetzt best effort fuer unprivilegierte Container
  - offen bleibt dort nur noch der spaetere Resolve einiger nicht-Block-Hardware-Intents

Gezielt geprueft:

- Syntax-/Import-Check der neuen Python-Module
- Contract-Test:
  - `tests/unit/test_runtime_hardware_blueprint_contract.py`
- lokaler API-Smoke-Check fuer `health`

Wichtig:

- der echte Runtime-Test im laufenden Stack ist inzwischen erfolgreich gelaufen
- der naechste Blocker ist jetzt der Ausbau ueber den nackten V0-Service hinaus

Live-Deploy erfolgreich:

- `jarvis-admin-api` neu gebaut und gestartet
- Blueprint `runtime-hardware` erfolgreich gesynct
- `runtime-hardware` erfolgreich ueber den Commander gestartet
- der jeweils aktuelle `runtime-hardware`-Container war bei den Redeploys `healthy`
- zusaetzlicher Laufzeit-Fix:
  - ein kaputter Write nach `/app/data/state/last_resources.json.tmp` konnte den Endpoint `GET /api/runtime-hardware/resources` auf `500` ziehen
  - dadurch zeigte `Simple > Neues Blueprint` zeitweise gar keine Geraete
  - der Store-/API-Pfad behandelt diese State-Snapshots jetzt nur noch best effort
  - nach dem Redeploy liefert der Endpoint wieder normal Ressourcen

Live geprueft:

- `GET /health`
- `GET /hardware/connectors`
- `GET /hardware/capabilities`
- `GET /hardware/resources`
- `GET /hardware/targets/container/<id>/state`
- `POST /hardware/validate`
- `POST /hardware/plan`
- `GET /api/runtime-hardware/health`
- `GET /api/runtime-hardware/connectors`
- `GET /api/runtime-hardware/capabilities`
- `GET /api/runtime-hardware/resources`
- `GET /api/commander/blueprints/{blueprint_id}/hardware`
- `POST /api/commander/blueprints/{blueprint_id}/hardware/plan`
- `POST /api/commander/blueprints/{blueprint_id}/hardware/validate`

Backend-Status jetzt:

- `hardware_intents` sind als strukturierte Blueprint-Daten im Backend vorhanden
- Commander kann diese `hardware_intents` gegen `runtime-hardware` planen und validieren
- Commander kann diese `hardware_intents` zusaetzlich kontrolliert aufloesen
- der Deploy-Pfad uebernimmt nur sichere Hardware-Resolutionen automatisch
- `mount_ref` ist nicht mehr nur ein Warnobjekt, sondern kann kontrolliert ueber Storage-Assets in echte Runtime-Mounts uebersetzt werden
- `mount_ref` beachtet jetzt dabei zusaetzlich:
  - reservierte Zielpfade
  - `policy_state=blocked`
  - `policy_state=read_only` vs. angeforderter Modus
- `block_device_ref` bleibt vorerst Warn-/Review-Objekt und wird nicht blind materialisiert
- der erste UI-Schritt ist jetzt vorhanden, aber bewusst noch begrenzt:
  - strukturierte Auswahl im `Simple`-Wizard
  - read-only Preview im klassischen Blueprint-Editor
  - echter Deploy-Opt-in fuer Block-Handoffs ist im Deploy-Dialog umgesetzt
- die `Simple`-Darstellung ist inzwischen deutlich staerker auf Docker-/Container-UX getrimmt:
  - sprechende `display_name`-/`display_secondary`-Metadaten
  - gruppierte Input-Geraete
  - versteckte Root-Hubs, `Monitor-Audio`- und sonstige Low-Level-Input-Eintraege
  - `Mount Refs` mit Groesse im Sekundaertext
  - `Block-Devices` ohne kleine technische Partitionen unter `1 GB`
- der Wizard-Renderpfad wurde danach auch frontendseitig noch einmal klarer gemacht:
  - `renderHardwareSection()` zeigt Hardware jetzt als Karten statt einfacher Checkbox-Zeilen
  - Suchfeld pro Kategorie
  - Aufteilung in `Empfohlen` und einklappbares `Erweitert`
  - Preset-Buttons pro Kategorie
    - `Gaming`, `Media`, `Desktop-App`
    - `Controller`, `Headset`
    - `NAS/Storage`
  - Status-Badges und kurze Klartext-Erklaerungen direkt an der Karte
  - Presets sind heuristisch und nutzen sichtbare Runtime-Hardware-Metadaten
    - keine fest verdrahteten Host-Resource-IDs
    - `NAS/Storage` nimmt dabei nicht mehr pauschal alle grossen Partitionen
    - sondern nur noch zuweisbare Storage-Kandidaten
  - sichtbare grosse `Block-Devices` bekommen jetzt zusaetzlich sprechendere Namen
    - z. B. `Read-only Partition 3`, `Read-only Partition 2`, `Service-Speicher`
- der echte Deploy-Opt-in fuer Block-Handoffs ist live verifiziert:
  - `block_apply_handoff_resource_ids_requested=["container::block_device_ref::/dev/sdd1"]`
  - `block_apply_handoff_resource_ids_applied=["container::block_device_ref::/dev/sdd1"]`
  - Docker-Mapping real vorhanden:
    - `/dev/sdd1 -> /dev/game-disk`
  - Deploy-Laufzeit fuer den echten Commander-Call:
    - vorher ca. `37s`
    - nach dem lokalen Resolver-Pfad ca. `0.3s`
- operativer Zusatzbefund vom 2026-03-27:
  - fuer Backend-Aenderungen am `runtime-hardware`-Service reicht ein Redeploy des Service-Containers allein nicht, wenn der Blueprint aus eingebetteten Quellen des `jarvis-admin-api`-Images baut
  - Reihenfolge fuer solche Aenderungen:
    1. `jarvis-admin-api` neu bauen/starten
    2. danach `runtime-hardware` neu deployen

Operativer Rahmen:

- die Commander-Parallelitaet wurde begleitend auf `5` Container angehoben
- Grund:
  - `runtime-hardware` ist jetzt selbst ein laufender Systemservice
  - begleitende Entwicklungscontainer sollen dadurch nicht mehr sofort an der alten `3`er-Grenze scheitern
- fuer reine Wizard-/CSS-Aenderungen gilt zusaetzlich:
  - `jarvis-webui` bind-mountet `adapters/Jarvis/js` und `adapters/Jarvis/static`
  - diese UI-Aenderungen brauchen daher im Normalfall keinen neuen `runtime-hardware`-Deploy
  - Browser-Reload / Hard-Refresh reicht

Wichtige reale Fixes waehrend des ersten Deploys:

1. Scope-Fix
   - erster Fehler:
     - `storage_scope_violation: mount '/sys' is outside scope 'runtime-hardware'`
   - Ursache:
     - Paketmanifest und Blueprint-Scope waren noch nicht deckungsgleich
   - Fix:
     - `marketplace/packages/runtime-hardware/package.json` um System-Mounts und Docker-Socket erweitert

2. Builder-Fix
   - zweiter Fehler:
     - Commander-Build via Docker-SDK konnte `/app/requirements.txt` im generierten Image nicht sehen
   - Ursache:
     - Heredoc-`RUN python3 - <<'PY'` war im genutzten Legacy-Builderpfad nicht robust
   - Fix:
     - `container_commander/runtime_hardware_blueprint.py` auf builder-kompatiblen `python3 -c`-Pfad umgestellt

---

## 1. Ziel des ersten Bauschnitts

Nach dem ersten v0-Bauschnitt soll Folgendes wahr sein:

1. `runtime-hardware` ist als eigenes installierbares Paket modelliert
2. `runtime-hardware` ist als eigener Blueprint deploybar
3. der Service startet als eigener Container
4. die API antwortet auf `health`, `resources`, `connectors`, `capabilities`, `plan`, `validate`
5. ein erster `container_connector` kann reale Host-/Container-Discovery liefern

Nicht Teil dieses ersten Bauschnitts:

- echte Live-Hardware-Manipulation
- allgemeines `apply`
- QEMU-Connector
- Remote-Agent-Connector
- vollstaendige UI

---

## 2. Geplanter Repo-Schnitt

## 2.1 Neuer Service-Bereich

Empfohlener neuer Code-Ort:

- `adapters/runtime-hardware/`

Begruendung:

- bestehende Jarvis-Services leben bereits unter `adapters/`
- der neue Dienst ist ein eigener API-Service und kein Untermodul von `admin-api`

Erwartete v0-Dateien:

- `adapters/runtime-hardware/Dockerfile`
- `adapters/runtime-hardware/requirements.txt`
- `adapters/runtime-hardware/main.py`
- `adapters/runtime-hardware/runtime_hardware/__init__.py`
- `adapters/runtime-hardware/runtime_hardware/models.py`
- `adapters/runtime-hardware/runtime_hardware/api.py`
- `adapters/runtime-hardware/runtime_hardware/store.py`
- `adapters/runtime-hardware/runtime_hardware/planner.py`
- `adapters/runtime-hardware/runtime_hardware/connectors/__init__.py`
- `adapters/runtime-hardware/runtime_hardware/connectors/base.py`
- `adapters/runtime-hardware/runtime_hardware/connectors/container_connector.py`

## 2.2 Marketplace-/Paketbereich

Neuer Paket-Ort:

- `marketplace/packages/runtime-hardware/`

Erwartete v0-Dateien:

- `marketplace/packages/runtime-hardware/package.json`
- `marketplace/packages/runtime-hardware/README.md`

Optional spaeter:

- Doku-/Addon-Dateien
- Connector-spezifische Hinweise

## 2.3 Blueprint-Integration

Die v0-Variante braucht einen echten Blueprint im bestehenden Commander-System.

Betroffene Bereiche spaeter:

- `container_commander/models.py`
- `container_commander/blueprint_store.py`
- `container_commander/mcp_tools.py`

Im ersten Schritt reicht:

- Blueprint definieren
- Blueprint deploybar machen
- noch keine `hardware_intents`-Erweiterung erzwingen

Stand jetzt:

- `hardware_intents` sind inzwischen backendseitig vorhanden
- der naechste Schritt ist nicht mehr das Speichern selbst, sondern die spaetere kontrollierte Aufloesung

---

## 3. Container-Skelett fuer v0

## 3.1 Laufzeitprofil

Technik fuer v0:

- Python-Service
- FastAPI
- Uvicorn

Begruendung:

- passt zum bestehenden Jarvis-Service-Stil
- kleine interne API ist schnell anschlussfaehig
- spaeter einfach ueber `admin-api` gatewaybar

## 3.2 Startverhalten

Der Service soll in v0:

- beim Start Konfiguration laden
- Connectoren registrieren
- Readiness auf Host-Sichtbarkeit und Docker-Socket pruefen
- danach die API bereitstellen

Kein v0-Ziel:

- lange Bootstrap-Sequenzen
- automatische Host-Manipulation

## 3.3 Persistenz im Container

Pfad-Mapping nach Vertrag:

- `/app/data/config`
- `/app/data/state`

Host-seitige Wurzel bleibt:

- `/data/services/runtime-hardware/config`
- `/data/services/runtime-hardware/data`

Empfohlene v0-Verwendung:

- `config` fuer Service-/Connector-Config
- `state` fuer Inventory-Cache und Plan-/Validate-Historie

---

## 4. Dockerfile-Plan fuer v0

Der Dockerfile-Schnitt soll bewusst klein bleiben.

V0-Dockerfile braucht:

1. Python-Base
2. `requirements.txt`
3. App-Code
4. Uvicorn-Startkommando

Soll in v0 **nicht** enthalten:

- PCI-/USB-Tooling fuer aktive Host-Manipulation
- libvirt- oder QEMU-Stacks
- udevd im Container
- privilegierte Hotplug-Helfer

Optional nuetzliche Tools in v0:

- `procps`
- `util-linux`
- `pciutils`
- `usbutils`

Aber nur, wenn sie wirklich fuer Discovery benoetigt werden.

---

## 5. API-Skelett fuer v0

## 5.1 Pflichtendpunkte

Der erste echte API-Schnitt:

- `GET /health`
- `GET /hardware/connectors`
- `GET /hardware/capabilities`
- `GET /hardware/resources`
- `GET /hardware/targets/{type}/{id}/state`
- `POST /hardware/plan`
- `POST /hardware/validate`

## 5.2 Erste Rueckgabeformen

Auch in v0 sollen Antworten bereits das spaetere Zielmodell spiegeln:

- `resources`
- `capabilities`
- `supported`
- `requires_restart`
- `requires_approval`
- `explanation`

Wichtig:

- `plan` darf in v0 ruhig oft `stage_for_recreate` oder `unsupported` zurueckgeben
- das ist kein Fehler, sondern ehrliche Capability-Modellierung

---

## 6. Container Connector v0

Der `container_connector` ist der erste echte Mehrwert.

## 6.1 Was er in v0 koennen muss

- Docker-Container lesen
- laufende Runtime-Ziele identifizieren
- Host-Ressourcen fuer Discovery einsammeln
- Attachbarkeit formal bewerten

## 6.2 Discovery-Quellen

Der Connector soll in v0 auslesen:

- Docker Engine ueber `/var/run/docker.sock`
- Host-Device-Sicht ueber `/dev`
- Host-Metadaten ueber `/run/udev`
- Topologie/Klassen ueber `/sys`
- Prozess-/Kernel-Kontext bei Bedarf ueber `/host_proc`

## 6.3 Erste Resource-Klassen

Fuer v0 reichen:

- `input`
- `usb`
- `device`
- `block_device_ref`
- `mount_ref`

`gpu_access` kann in v0 zunaechst nur als erkannter Capability-Hinweis auftauchen, ohne echte Attach-Logik.

## 6.4 Erste Capability-Regeln

Fuer Container in v0 gilt standardmaessig:

- vieles ist nur `stage_for_recreate`
- weniges ist `supported` als Discovery-/Plan-Ebene
- fast nichts ist `live_attach`

Genau diese Ehrlichkeit ist gewollt.

---

## 7. Paketbau fuer v0

## 7.1 package.json

Das Paket `runtime-hardware` soll enthalten:

- `id`
- `name`
- `version`
- `package_type`
- `blueprints`
- `storage.scope`
- `storage.paths`
- `notes`

Optional:

- Access-Link fuer Debug, falls Host-Port spaeter geoeffnet wird

## 7.2 README

Das README fuer v0 soll knapp erklaeren:

- dass es ein interner Discovery-/Plan-Service ist
- dass `container_connector` zuerst kommt
- dass QEMU/Remote spaeter folgen
- dass `apply` in v0 bewusst nicht der Schwerpunkt ist

---

## 8. Blueprint-Bau fuer v0

Der Blueprint `runtime-hardware` soll in v0 enthalten:

- Image-/Build-Verweis auf den neuen Service
- Persistenzpfade
- interne API-Port-Freigabe
- benoetigte Read-Only-Mounts
- Docker-Socket-Mount
- keine pauschalen Hochrisiko-Rechte

Wichtige Eigenschaften:

- `privileged = false`
- keine pauschalen `cap_add`
- Read-Only-Mounts fuer Host-Discovery

Der Blueprint ist in v0 ein Systemdienst-Blueprint, kein Nutzer-Workload.

---

## 9. Compose-/Deploy-Integration

Es gibt zwei moegliche erste Pfade:

1. direkte Compose-Ergaenzung im lokalen Jarvis-Setup
2. Marketplace-/Blueprint-getriebener Deploy ueber den Commander

Empfehlung:

- zuerst den Service im Repo als deploybaren Blueprint modellieren
- lokal kann zusaetzlich eine Compose-Ergaenzung fuer schnelle Entwicklung sinnvoll sein
- kanonisch soll aber der Blueprint-/Paketpfad bleiben

Damit ist `standalone installierbar wie die Blueprints` von Anfang an mitgedacht.

---

## 10. Admin-API-Gateway

V0 braucht noch keine volle UI, aber einen klaren Zugangspfad.

Empfohlener erster Integrationsschritt:

- `admin-api` bekommt einen kleinen Proxy/Gateway-Pfad zu `runtime-hardware`

Vorteil:

- Frontend spricht weiter mit der bekannten Admin-Schicht
- der neue Service bleibt intern
- spaetere Auth-/Policy-Logik bleibt zentraler

Nicht Teil des ersten Bauschnitts:

- komplette UI

---

## 11. Reihenfolge der Umsetzung

## Schritt 1: Service-Skelett anlegen

- neuer Ordner `adapters/runtime-hardware/`
- Dockerfile
- requirements
- FastAPI-Startpunkt
- `GET /health`

Definition of Done:

- Container startet
- Health-Endpunkt antwortet

Status 2026-03-26:

- im Repo erledigt
- im echten Containerlauf erfolgreich verifiziert

## Schritt 2: Core-Modelle anlegen

- `HardwareResource`
- `RuntimeCapability`
- `AttachmentPlan`
- `AttachmentState`

Definition of Done:

- API kann strukturierte leere/basale Antworten geben

## Schritt 3: Connector-Basis anlegen

- `connectors/base.py`
- Registry fuer Connectoren
- `container_connector` als erster realer Connector

Definition of Done:

- `GET /hardware/connectors` zeigt `container`

Status 2026-03-26:

- im Repo erledigt

## Schritt 4: Discovery fuer den container_connector

- Docker-Container lesen
- Host-Devices klassifizieren
- erste Ressourcenlisten liefern

Definition of Done:

- `GET /hardware/resources` liefert reale Host-/Runtime-nahe Ressourcen

Status 2026-03-26:

- Codepfad implementiert
- im deployten Container erfolgreich geprueft

## Schritt 5: Capability-/Plan-Endpunkte

- `GET /hardware/capabilities`
- `POST /hardware/plan`
- `POST /hardware/validate`

Definition of Done:

- fuer reale Targets kommen formale Antworten mit `supported`/`requires_restart`/`unsupported`

## Schritt 6: Marketplace-Paket + Blueprint

- `marketplace/packages/runtime-hardware/`
- `package.json`
- `README.md`
- Blueprint `runtime-hardware`

Definition of Done:

- Service ist ueber den bestehenden Paket-/Blueprint-Pfad installierbar

Status 2026-03-26:

- Paket und Blueprint-Seed sind angelegt
- echter Install-/Deploy-Test erfolgreich durchgezogen

## Schritt 7: interner Admin-API-Zugang

- kleiner Gateway-Pfad in `admin-api`

Definition of Done:

- der Service ist aus Jarvis intern sauber erreichbar

---

## 12. Akzeptanzkriterien fuer v0

V0 ist erreicht, wenn:

1. `runtime-hardware` als eigener Service deploybar ist
2. ein installierbares Paket `runtime-hardware` existiert
3. ein Blueprint `runtime-hardware` existiert
4. der Service Host-Ressourcen lesen kann
5. der Service laufende Container lesen kann
6. `resources`, `connectors`, `capabilities`, `plan`, `validate` funktionieren
7. der Service ohne `privileged` und ohne pauschale Schreibrechte auf Host-Geraete startet

---

## 13. Bewusste Nicht-Ziele waehrend des ersten Bauschnitts

Nicht in dieselbe Runde ziehen:

- `hardware_intents` in voller Blueprint-Tiefe
- komplette Frontend-UI
- QEMU-Connector
- Remote-Agent-Connector
- `apply` mit echter Live-Hardware-Aktion
- komplexe Approval-Workflows

Wenn das zu frueh hineingezogen wird, wird der v0-Container wieder zu breit.

---

## 14. Naechster sinnvoller Umsetzungsschritt

Der naechste konkrete Schritt im Code ist:

1. `container_connector` nach den ersten Realdaten weiter aufteilen/haerten
2. die `block_apply_*`-Vertraege und Handoffs weiter runtime-neutral schneiden
3. danach den Container-Engine-Adapter weiter vorbereiten
   - weiter deaktiviert
   - weiter ohne Auto-Apply
4. `qemu_connector` weiter als vorbereiteten Folgeschritt behandeln

Kurzform:

- V0-Service steht
- Discovery gegen echte Laufumgebung steht
- Gateway und Commander-Backend-Pfad stehen
- erste UI und der Deploy-Opt-in stehen
- jetzt Haertung, Vertragsbereinigung und danach weiterer Ausbau
