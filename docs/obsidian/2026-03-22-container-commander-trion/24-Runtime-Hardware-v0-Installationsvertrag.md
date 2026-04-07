# Runtime Hardware v0 Installationsvertrag

Erstellt am: 2026-03-26

Bezug:

- [[23-Runtime-Hardware-Modul-Implementationsplan]]
- [[25-Runtime-Hardware-v0-Containerbauplan]]

## Zweck dieser Notiz

Diese Notiz definiert den **v0-Installationsvertrag** fuer den neuen Service `jarvis-runtime-hardware`.

Sie beantwortet fuer die erste reale Anlage des Services:

- wie das Paket modelliert wird
- wie der erste Blueprint aussehen soll
- welche Host-Sichtbarkeit der Container bekommt
- welche Rechte und Grenzen v0 haben soll
- welche Persistenz und Ports vorgesehen sind
- was in v0 bewusst **noch nicht** aktiviert wird

Wichtig:

- Das ist ein Installationsvertrag, kein Vollkonzept fuer alle spaeteren Hardwarefaelle.
- Ziel ist ein sauber installierbarer, standalone-faehiger Startpunkt.
- Der Vertrag ist so geschnitten, dass spaetere Connectoren fuer `qemu` und `remote_agent` anschliessen koennen, ohne den Service neu zu erfinden.

## Aktueller Status zum Vertrag

Stand: 2026-03-26

Der Vertrag ist nicht mehr nur theoretisch, sondern bereits in einen ersten v0-Codepfad **und einen erfolgreichen Live-Deploy** uebersetzt worden.

Bereits materialisiert:

- Paketpfad:
  - `marketplace/packages/runtime-hardware/`
- Servicepfad:
  - `adapters/runtime-hardware/`
- Blueprint-Seed:
  - `container_commander/runtime_hardware_blueprint.py`

Wichtige praktische Einordnung:

- der v0-Blueprint baut aktuell ein eigenes Service-Image aus den Repo-Dateien
- der Service ist damit nicht nur als abstrakte Paketidee beschrieben, sondern als realer Commander-Blueprint vorbereitet
- der Vertrag bleibt dabei unveraendert gueltig: `privileged = false`, Host-Lesesicht, Docker-Socket, keine aggressive Live-Manipulation in v0

Live bestaetigt:

- der Service laeuft erfolgreich als Container
- Host-Port `8420/tcp` ist aktiv
- der laufende Stand ist `healthy`
- die Discovery-/Plan-/Validate-Pfade arbeiten gegen die echte Laufumgebung
- der Zugriff ueber `admin-api` als Gateway ist real vorhanden
- Blueprints koennen `hardware_intents` jetzt backendseitig strukturiert speichern
- Blueprints koennen ueber Commander gegen `runtime-hardware` geplant und validiert werden

---

## 1. Ziel des v0

`jarvis-runtime-hardware` soll in v0 bereits als eigener installierbarer Jarvis-Service existieren.

v0 garantiert:

- der Service ist als eigenes Paket installierbar
- der Service hat einen eigenen Blueprint
- der Service hat persistente Datenpfade
- der Service kann Host-Ressourcen fuer Discovery lesen
- der Service kann eine API fuer Inventory/Capability/Plan bereitstellen
- Blueprints koennen strukturierte `hardware_intents` speichern
- `admin-api` und Commander koennen `hardware_intents` gegen `runtime-hardware` mit `plan` und `validate` pruefen

v0 garantiert **nicht**:

- allgemeines Live-Attach fuer Container
- vollwertiges PCI-Passthrough
- QEMU-Hotplug
- Remote-Agent-Federation
- automatische Storage-Materialisierung

Kurz:

v0 ist ein installierbarer Discovery-/Planungs-Service, noch kein vollwertiger Hardware-Orchestrator.

---

## 2. Paketform

Der Service soll als eigenes Marketplace-Paket entstehen, analog zu den bestehenden installierbaren Paketen.

Empfohlene Identitaet:

- `package_id`: `runtime-hardware`
- `name`: `Runtime Hardware`
- `package_type`: `composite_addon`
- `blueprints`: `["runtime-hardware"]`

Begruendung:

- der Service ist ein eigener installierbarer Baustein
- er soll spaeter zusaetzliche Dateien, Dokumentation und evtl. Connector-spezifische Begleitdateien mitbringen koennen
- die bestehende Marketplace-/Blueprint-Logik passt bereits zu diesem Muster

---

## 3. Blueprint-Identitaet

Empfohlene Blueprint-Identitaet:

- `blueprint_id`: `runtime-hardware`
- `runtime`: `docker`
- `name`: `Runtime Hardware Service`
- `description`: `Generischer Hardware-, Attachment- und Capability-Service fuer Jarvis`

Der Blueprint soll in v0 nur den Service selbst deployen, nicht bereits QEMU oder externe Agents materialisieren.

---

## 4. Persistenz

Empfohlener Storage-Scope:

- `scope.name`: `runtime-hardware`

Empfohlene persistente Pfade:

- `/data/services/runtime-hardware/config`
- `/data/services/runtime-hardware/data`

Verwendung:

- `config`
  - Connector-Konfiguration
  - lokale Service-Konfiguration
  - spaeter Connector-Registrierung und Policies
- `data`
  - Cache fuer Inventar
  - Job-/Audit-Status
  - Plan-/Validate-Historie

Wichtig:

- keine Storage-Provisionierung fuer Fremdservices in diesem Scope
- kein Mitspeichern fremder Blueprint-Wahrheit

---

## 5. Netzwerk und Ports

v0 braucht nur eine interne API.

Empfehlung:

- interner Container-Port: `8420/tcp`
- externer Host-Port: zunaechst optional

v0-Default:

- Service im internen Jarvis-Netz erreichbar
- Zugriff ueber `admin-api` als Gateway bevorzugt

Optional fuer Debug:

- temporaerer Host-Port `8420:8420`

Begruendung:

- der Service ist primar ein interner Systemdienst
- die UI soll spaeter ueber `admin-api` sprechen
- ein offener Host-Port sollte kein Installationszwang fuer v0 sein

---

## 6. Host-Sichtbarkeit fuer v0

Der Container braucht in v0 **Lesesicht**, nicht sofort Vollzugriff.

Empfohlene Read-Only-Mounts:

- `/sys:/sys:ro`
- `/run/udev:/run/udev:ro`
- `/dev:/dev:ro`
- `/proc:/host_proc:ro`

Optional, wenn sauber enger schneidbar:

- `/sys/bus/pci:/sys/bus/pci:ro`
- `/sys/class:/sys/class:ro`
- `/sys/block:/sys/block:ro`
- `/sys/class/block:/sys/class/block:ro`

Warum diese Sichtbarkeit:

- PCI-/USB-/Input-/Block-Discovery braucht Host-nahe Informationen
- `/run/udev` erlaubt Metadaten zu Geraeten
- `/dev` erlaubt Sicht auf Device-Nodes
- `/sys` erlaubt Klassifikation und Topologie

Wichtig:

- v0 soll **nicht** blind mit Schreibrechten auf `/dev` oder `/sys` starten
- v0 soll Discovery koennen, nicht schon beliebige Host-Manipulation

---

## 7. Docker-/Runtime-Integration in v0

Der Service muss in v0 Container-Ziele inspizieren koennen.

Empfohlene Anbindung:

- `/var/run/docker.sock:/var/run/docker.sock`

Begruendung:

- der erste Connector ist `container_connector`
- ohne Docker-Socket kann der Service laufende Container, Konfigurationen und moegliche Attach-Ziele nicht verifizieren

Wichtig:

- der Docker-Socket ist hochprivilegiert
- deshalb muss der Service als interner Admin-Service behandelt werden
- Approval-/Risk-Logik darf spaeter nicht fehlen

---

## 8. Rechte- und Sicherheitsmodell fuer v0

v0 soll so klein wie moeglich starten.

Default fuer v0:

- `privileged = false`
- keine pauschalen `cap_add`
- Read-Only-Host-Mounts fuer Discovery
- Docker-Socket nur fuer Runtime-Inspektion

Bewusst **nicht** in v0:

- `privileged: true`
- Schreibrechte auf `/sys`
- Schreibrechte auf `/dev`
- pauschaler Zugriff auf PCI bind/unbind
- allgemeines Host-Hotplug aus dem Container heraus

Begruendung:

- das wuerde den Service sofort zu breit und zu riskant machen
- v0 soll ein sicherer Discovery-/Plan-Service sein
- echte Apply-Schritte koennen spaeter pro Connector gezielt erweitert werden

---

## 9. API-Verhalten in v0

Die v0-API soll bereits stabil nutzbar sein, auch wenn `apply` noch eingeschraenkt ist.

v0-Endpunkte:

- `GET /health`
- `GET /hardware/resources`
- `GET /hardware/connectors`
- `GET /hardware/capabilities`
- `GET /hardware/targets/{type}/{id}/state`
- `POST /hardware/plan`
- `POST /hardware/validate`

In v0 bewusst noch eingeschraenkt:

- `POST /hardware/apply`
- `POST /hardware/detach`

Empfohlener v0-Status fuer `apply/detach`:

- erlaubt nur trockene Plaene oder klar markierte `unsupported`-/`stage_for_recreate`-Antworten
- noch keine aggressive Live-Manipulation

Aktueller Stand:

- implementiert wurden bisher:
  - `GET /health`
  - `GET /hardware/resources`
  - `GET /hardware/connectors`
  - `GET /hardware/capabilities`
  - `GET /hardware/targets/{type}/{id}/state`
  - `POST /hardware/plan`
  - `POST /hardware/validate`
- `apply` und `detach` sind weiterhin bewusst nicht Teil des ersten Slices

Live verifiziert:

- `GET /health` -> `status=ok`
- `GET /hardware/connectors` -> `container`
- `GET /hardware/capabilities` -> 6 Capability-Eintraege
- `GET /hardware/resources` -> reale Discovery-Daten
- `GET /hardware/targets/.../state` -> laufende Container-State-Auskunft
- `POST /hardware/validate` -> erfolgreich gegen reales Containerziel
- `POST /hardware/plan` -> liefert gewuenscht `stage_for_recreate` statt falschem Live-Attach-Versprechen
- `GET /api/runtime-hardware/*` -> erfolgreich ueber `admin-api`
- `GET /api/commander/blueprints/{blueprint_id}/hardware` -> erfolgreich
- `POST /api/commander/blueprints/{blueprint_id}/hardware/plan` -> erfolgreich
- `POST /api/commander/blueprints/{blueprint_id}/hardware/validate` -> erfolgreich
- echter Demo-Blueprint mit `hardware_intents`:
  - `plan.summary = requires_recreate`
  - erste Aktion `stage_for_recreate`
  - `validate.valid = true`

---

## 10. Connector-Umfang in v0

In v0 ist nur ein echter Connector Pflicht:

- `container_connector`

V0-Aufgaben des `container_connector`:

- laufende Container lesen
- Blueprints/Runtime-Ziele normiert referenzieren
- Host-Ressourcen gegen Container-Moeglichkeiten abgleichen
- Capability-Matrix fuer `container` liefern

In v0 nur als vorbereitete Platzhalter:

- `qemu_connector`
- `remote_agent_connector`

Begruendung:

- wir muessen zuerst das Kernmodell gegen einen echten Runtime-Typ haerten
- `container` ist der naechste real nutzbare Pfad im bestehenden System

---

## 11. Installationsform im Marketplace

Das Paket `runtime-hardware` soll dieselbe Grundform haben wie andere installierbare Pakete:

- `package.json`
- eigener Blueprint `runtime-hardware`
- optionale `README.md`
- spaeter optionale Zusatzdateien fuer Connectoren oder Doku

Empfohlener Inhalt des spaeteren `package.json`:

- Paketmetadaten
- referenzierter Blueprint
- `storage.scope`
- notwendige Persistenzpfade
- optionale Access-Links
- Notizen zur Sicherheitsrolle des Dienstes

Access-Link in v0:

- optional `Open Runtime Hardware API`
- nur wenn ein Host-Port fuer Debug tatsaechlich freigegeben wird

---

## 12. Beziehung zu Blueprints

Der Service selbst ist ueber einen Blueprint installierbar.

Zusaetzlich ist er spaeter ein Dienst fuer andere Blueprints.

Das heisst:

- `runtime-hardware` ist selbst ein installierbarer Blueprint
- andere Blueprints referenzieren spaeter `hardware_intents`
- die eigentliche Hardware-Planung laeuft dann ueber den Dienst

Wichtig:

- der Dienst speichert nicht die kanonische Blueprint-Wahrheit
- die Blueprint-Wahrheit bleibt im `Container Commander`

---

## 13. V0-Installationsablauf

Empfohlene Reihenfolge:

1. Marketplace-Paket `runtime-hardware` anlegen
2. Blueprint `runtime-hardware` anlegen
3. Storage-Scope `runtime-hardware` registrieren
4. Service deployen
5. Healthcheck verifizieren
6. Discovery-Endpunkte gegen reale Host-Ressourcen pruefen
7. `admin-api` als Gateway andocken

Erfolgsbedingung fuer v0:

- der Dienst ist installierbar wie andere Pakete
- der Dienst ueberlebt Restarts mit persistenter Konfiguration
- der Dienst kann Host-Ressourcen inventarisieren
- der Dienst kann Container-Ziele inspizieren

---

## 14. Bewusste Nicht-Ziele fuer v0

Folgendes wird in v0 absichtlich verschoben:

- direkte PCI bind/unbind Steuerung
- libvirt-/QEMU-Hotplug
- USB-Rechteeskalation aus dem Container heraus
- produktive Live-Detach-/Live-Attach-Pfade
- Multi-Agent-Hardware-Federation
- Storage-Broker-Ersatzlogik

---

## 15. Offene Entscheidungen vor der Umsetzung

Diese Punkte muessen vor dem echten Bau noch final entschieden werden:

1. Soll der Service direkt auf einem Host-Port erreichbar sein oder nur intern ueber `admin-api`?
2. Soll v0 `/dev` voll read-only sehen oder nur selektive Teilpfade?
3. Soll `apply` in v0 ganz deaktiviert sein oder bereits `stage_for_recreate` materialisieren duerfen?
4. Wo liegt die kleine v0-Datenhaltung: SQLite im Service selbst oder bestehende zentrale Persistenz?
5. Soll der Service spaeter als eigener Frontend-Eintrag sichtbar sein oder zuerst nur indirekt ueber Blueprint-/Container-UI?

---

## 16. Empfohlene Entscheidungsbasis

Meine Empfehlung fuer den Start:

- eigener Service-Container: ja
- installierbar ueber Marketplace/Blueprint: ja
- Host-Port in v0: nein, nur intern ueber `admin-api`
- Docker-Socket in v0: ja
- `/sys`, `/run/udev`, `/dev`, `/proc` read-only: ja
- `privileged` in v0: nein
- `apply live` in v0: nein
- `plan + validate + stage_for_recreate` in v0: ja

Kurzform:

`jarvis-runtime-hardware` startet als sicher geschnittener Discovery-/Plan-Service mit installierbarem Paketvertrag, nicht sofort als vollprivilegierter Hotplug-Controller.

Naechster operativer Schritt:

- Gateway-Pfad in `admin-api` ist erledigt
- `hardware_intents` im Backend-Schema sind erledigt
- als naechstes die kontrollierte Aufloesung von `hardware_intents` in spaetere Runtime-Overrides vorbereiten
- UI erst danach andocken
