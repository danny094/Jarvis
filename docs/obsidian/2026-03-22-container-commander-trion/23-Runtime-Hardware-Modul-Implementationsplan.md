# Runtime Hardware Modul Implementationsplan

Erstellt am: 2026-03-26

## Zweck dieser Notiz

Diese Notiz beschreibt den Implementationsplan fuer ein neues, generisches `runtime_hardware`-Modul als eigenen Service/Container.

Ziel ist **nicht** ein Gaming-Sonderpfad, sondern eine erweiterbare Hardware-/Attachment-Schicht fuer mehrere Runtime-Typen:

- `container`
- `qemu`
- spaeter `remote_agent`

Die Notiz beantwortet:

- welches Zielbild das neue Modul haben soll
- welche Grenzen gegenueber `Container Commander` und `Storage Broker` gelten
- wie das Domaaenenmodell aussehen soll
- welche API-/UI-Schnitte gebraucht werden
- in welcher Reihenfolge die Implementierung sinnvoll ist

## Aktueller Umsetzungsstand

Stand: 2026-03-27

Der erste echte v0-Schnitt wurde angelegt **und bereits erfolgreich im laufenden Stack deployed**.

Gebaut:

- neuer Service unter `adapters/runtime-hardware/`
- neues Marketplace-Paket unter `marketplace/packages/runtime-hardware/`
- neuer Blueprint-Generator unter `container_commander/runtime_hardware_blueprint.py`
- Startup-Hook in `adapters/admin-api/main.py`, damit `runtime-hardware` beim Admin-API-Start angelegt wird

Wichtige Repo-Einstiegspunkte:

- Service-Startpunkt:
  - `adapters/runtime-hardware/main.py`
- API:
  - `adapters/runtime-hardware/runtime_hardware/api.py`
- Modelle:
  - `adapters/runtime-hardware/runtime_hardware/models.py`
- Plan-Logik:
  - `adapters/runtime-hardware/runtime_hardware/planner.py`
- erster Connector:
  - `adapters/runtime-hardware/runtime_hardware/connectors/container_connector.py`
- Paketmanifest:
  - `marketplace/packages/runtime-hardware/package.json`
- Blueprint-Seed:
  - `container_commander/runtime_hardware_blueprint.py`

Seit dem ersten Deploy zusaetzlich umgesetzt:

- Gateway-Pfad ueber `admin-api` ist real vorhanden
- `hardware_intents` sind backendseitig im Blueprint-Modell verankert
- Commander-seitiger Hardware-Pfad fuer Blueprints ist real vorhanden
- eigenes Commander-Modul fuer die kontrollierte Hardware-Aufloesung ist real vorhanden:
  - `container_commander/hardware_resolution.py`
- `start_container()` uebernimmt jetzt klare `device`-/`input`-/`usb`-Resolutionen automatisch in Runtime-Overrides
- `block_device_ref` bleibt bewusst ausserhalb der Auto-Materialisierung und erscheint weiterhin als Deploy-Warnung
- `mount_ref` wird jetzt aus veroeffentlichten Storage-Assets in echte Runtime-Mounts materialisiert, aber nur wenn ein expliziter `container_path` im Intent gesetzt ist
- `mount_ref` ist jetzt zusaetzlich policy-gehärtet:
  - reservierte Zielpfade wie `/proc`, `/sys`, `/dev`, `/run`, `/etc`, `/usr`, `/boot`, `/var/run`, `/workspace` werden blockiert
  - `policy_state=blocked` sperrt Materialisierung komplett
  - `policy_state=read_only` sperrt jede `rw`-Materialisierung
- `block_device_ref` ist jetzt in ein eigenes Commander-Modul `container_commander/hardware_block_resolution.py` ausgelagert
- `block_device_ref` hat jetzt zusaetzlich einen getrennten Apply-Vorbereitungs- und Plan-Pfad:
  - `container_commander/hardware_block_apply.py`
  - `container_commander/hardware_block_apply_plan.py`
- `runtime-hardware plan` transportiert dafuer jetzt Ressourcen-Metadaten bis in den Commander-Resolver
- erste harte `block_device_ref`-Regeln greifen bereits:
  - `system` / `is_system`
  - `policy_state=blocked`
  - `read_only + rw`
  - `allowed_operations` ohne `assign_to_container`
- der Resolve-Pfad liefert jetzt nicht nur Warnings, sondern auch:
  - `block_apply_previews`
  - spaetere, noch deaktivierte `block_apply_candidates`
- `block_apply_previews` enthalten jetzt bereits:
  - `target_runtime`
  - `target_runtime_path`
  - `candidate_runtime_binding`
  - `requirements`
  - `blockers`
- container-spezifische Details bleiben erhalten, aber gekapselt unter:
  - `runtime_parameters.container.candidate_container_path`
  - `runtime_parameters.container.candidate_device_override`
- `block_apply_candidates` bleiben aktuell bewusst deaktiviert:
  - `activation_state=disabled_until_engine_support`
  - `activation_reason=future_engine_block_apply_enablement`
- der erste Container-spezifische Adapter dafuer liegt jetzt separat in:
  - `container_commander/hardware_block_container_adapter.py`
- dieser Adapter erzeugt heute nur deaktivierte `block_apply_container_plans`
  - keine Engine-Integration
  - kein Auto-Apply
- der erste vorbereitete Engine-Handover dafuer liegt jetzt separat in:
  - `container_commander/hardware_block_engine_handoff.py`
- dieser Handover erzeugt heute nur deaktivierte `block_apply_engine_handoffs`
  - keine automatische Uebernahme in `start_container()`
  - kein Auto-Apply
- der erste explizite Engine-Opt-in dafuer liegt jetzt separat in:
  - `container_commander/hardware_block_engine_opt_in.py`
- `start_container()` akzeptiert jetzt optional `block_apply_handoff_resource_ids`
  - nur explizit ausgewaehlte Handoffs werden in `device_overrides` uebernommen
  - Standard bleibt aus
  - Approval-/Resume-Pfade transportieren die Auswahl jetzt mit
- der Read-/Preview-Pfad ist jetzt sichtbar:
  - `GET /api/commander/blueprints/{id}?hardware_preview=true`
  - `GET /api/commander/blueprints/{id}/hardware`
  - `POST /api/commander/blueprints/{id}/hardware/resolve`
- die kompakten Payloads enthalten jetzt:
  - `hardware_preview.summary`
  - `resolution_preview`
  - `block_apply_handoff_resource_ids_hint`
  - `engine_opt_in_available`
- der Deploy-Response enthaelt jetzt zusaetzlich:
  - `hardware_deploy.block_apply_handoff_resource_ids_requested`
  - `hardware_deploy.block_apply_handoff_resource_ids_applied`
  - `hardware_deploy.hardware_resolution_preview`
- der echte Deploy-Pfad wurde danach noch einmal gehaertet:
  - im `admin-api`-/Commander-Kontext nutzt `container_commander/hardware_resolution.py` fuer Deploy-Resolution jetzt bevorzugt die lokal eingebetteten `runtime-hardware`-Module unter `/app/adapters/runtime-hardware`
  - Grund:
    - der HTTP-Pfad zu `runtime-hardware` war fuer `POST /hardware/plan` im Live-Deploy ueber Host-/Gateway-Fallbacks zwar prinzipiell erreichbar, aber operativ unzuverlaessig und langsam
    - Folge waren vorher echte Deploys mit `runtime_hardware_resolution_unavailable` oder Wartezeiten im Bereich ~37s
  - der lokale Fallback bleibt dabei nicht blind:
    - `storage-broker` wird fuer Disk-Metadaten weiter direkt befragt
    - Commander-Storage-Assets werden lokal aus `container_commander.storage_assets` gelesen
  - der allgemeine Standalone-Service `runtime-hardware` und der API-Gateway-Pfad bleiben trotzdem bestehen
- live verifiziert fuer den echten End-to-End-Deploy:
  - `POST /api/commander/containers/deploy`
  - `block_apply_handoff_resource_ids_requested=["container::block_device_ref::/dev/sdd1"]`
  - `block_apply_handoff_resource_ids_applied=["container::block_device_ref::/dev/sdd1"]`
  - `hardware_resolution_preview.supported=true`
  - Docker-Inspect:
    - `/dev/sdd1 -> /dev/game-disk`
  - Laufzeit des Deploy-Calls:
    - vorher ~37s
    - danach ~0.3s
- der erste Frontend-Anschluss ist jetzt begonnen:
  - `adapters/Jarvis/js/apps/terminal/blueprint-simple.js`
  - `adapters/Jarvis/js/apps/terminal/blueprint-editor.js`
  - `adapters/Jarvis/js/apps/terminal/preflight.js`
  - `adapters/Jarvis/js/apps/terminal/runtime-hardware-ui.js`
- der `Simple`-Wizard nutzt `runtime-hardware/resources` jetzt als echte Auswahlquelle und speichert Auswahl bewusst als strukturierte `hardware_intents`
  - nicht mehr als Rueckfaltung in rohe `devices`
- im selben Overview-Pfad unterstuetzt der `Simple`-Wizard inzwischen auch direkt ein eigenes Dockerfile
- fuer Storage-Hardware werden dort jetzt nicht mehr nur leere Policies gespeichert:
  - `block_device_ref` uebernimmt fuer `managed_rw` jetzt direkt `policy.mode=rw`
  - `mount_ref` uebernimmt vorhandene Source-Modi (`ro`/`rw`) als Strukturwert
- die Frontend-Trennung ist jetzt bewusst festgezogen:
  - `Hardware` = strukturierter Runtime-Hardware-Pfad
  - `Raw Runtime` = direkter Experten-/Escape-Hatch-Pfad
- im Blueprint-Editor ist `Hardware Preview` jetzt bewusst read-only
  - kein irrefuehrender lokaler Opt-in mehr im Editor
  - neue Blueprints zeigen dort jetzt einen ehrlichen Hinweis statt eines haengenden Loaders
- `input` ist im Frontend-Wizard jetzt als eigene Hardware-Kategorie sichtbar
- die Benennungslogik fuer Hardware ist jetzt frontendseitig vereinheitlicht:
  - gemeinsamer UI-Helfer in `adapters/Jarvis/js/apps/terminal/runtime-hardware-ui.js`
  - `blueprint-simple`, `preflight` und `blueprint-editor` nutzen jetzt dieselbe Anzeige fuer `label` / `vendor` / `product` / `host_path`
  - rohe Resource-IDs und `/dev/...`-Pfade sind damit nicht mehr automatisch das Primaerlabel
- der Deploy-Dialog zeigt opt-in-faehige Hardware-Handoffs jetzt mit sprechenden Namen statt nur Resource-IDs
- die read-only Hardware-Preview im Blueprint-Editor nutzt jetzt dieselbe Benennungslogik
- der `Simple`-Wizard wurde danach noch einmal klarer auf Docker-/Container-Nutzung getrimmt:
  - Kategorien jetzt sprechender benannt:
    - `Eingabe`
    - `Grafik & Systemzugriff`
    - `USB-Zubehoer`
    - `Direkte Datentraeger`
    - `Speicherpfade`
  - Hardware wird nicht mehr als reine Checkbox-Zeile, sondern als Card dargestellt
  - pro Kategorie gibt es jetzt:
    - clientseitige Suche
    - `Empfohlen`-Bereich
    - eingeklappten `Erweitert`-Bereich
  - Presets sind jetzt im Wizard sichtbar:
    - z. B. `Gaming`, `Media`, `Desktop-App`, `Controller`, `Headset`, `NAS/Storage`
  - Presets sind bewusst heuristisch umgesetzt
    - nicht ueber fest verdrahtete Host-IDs
    - sondern ueber sichtbare Runtime-Hardware-Metadaten
    - `NAS/Storage` waehlt dabei nicht mehr pauschal alle grossen Partitionen
    - sondern nur noch sinnvolle, zuweisbare Storage-Kandidaten
  - Cards zeigen jetzt zusaetzlich:
    - Status-Badges wie `Funktioniert direkt`, `Nur mit Review`, `Systemkritisch`
    - optionale Kontext-Badges wie `GPU`
    - kurze Klartext-Erklaerungen pro Ressourcentyp
- live verifiziert: bei Whole-Disk-Review-Faellen entstehen weiterhin weder `block_apply_candidates` noch `block_apply_container_plans`
- live verifiziert: bei der erlaubten Partition `container::block_device_ref::/dev/sdd1` entstehen jetzt erstmals
  - ein echter `block_apply_candidate`
  - ein echter, weiter deaktivierter `block_apply_container_plan`
  - ein echter, weiter deaktivierter `block_apply_engine_handoff`
  - Binding `/dev/sdd1:/dev/game-disk`
- der Deploy-Dialog glättet diesen Pfad inzwischen weiter:
  - fuer `simple-wizard`-Auswahlen werden opt-in-faehige `block_apply_handoff_resource_ids` jetzt standardmaessig vorselektiert
  - damit zieht eine explizit im Wizard ausgewaehlte `managed_rw`-Partition beim normalen UI-Deploy automatisch in den Opt-in-Pfad mit hinein, ohne die Backend-Sicherungen zu entfernen
- ein separater `gaming-test`-Deploy hat parallel noch einen Folgepunkt offengelegt:
  - der fruehere `mount: /proc: permission denied` sass im `steam-headless`-Base-Image und nicht im Storage-Broker
  - fuer abgeleitete Gaming-Dockerfiles wird der Flatpak-Init deshalb jetzt best effort gepatched
  - verbleibend offen ist dort nur noch die spaetere Aufloesung einiger nicht-Block-Hardware-Intents (`resource_not_found`)
- backendseitig ist die Input-Discovery inzwischen ebenfalls nachgeschaerft:
  - `adapters/runtime-hardware/runtime_hardware/connectors/container_connector.py` liest fuer `/dev/input/event*` jetzt zusaetzlich `/sys/class/input/<event>/device/name`
  - dadurch liefert `runtime-hardware/resources` fuer Input-Ressourcen nicht mehr nur rohe `event*`-Eintraege
- die UX-/Anzeige-Haertung fuer `Simple` ist inzwischen zusaetzlich real vorhanden:
  - neues Anzeige-/Filtermodul:
    - `adapters/runtime-hardware/runtime_hardware/connectors/container_display.py`
  - Input-Ressourcen werden fuer `Simple` jetzt logisch gruppiert
    - z. B. `Mouse passthrough` + `Mouse passthrough (absolute)` -> ein sichtbarer Eintrag `Maus`
  - technische Audio-/Bus-Eintraege werden in `Simple` jetzt verborgen
    - z. B. `HD-Audio`, `Video Bus`, `Monitor-Audio`
  - USB-Ressourcen zeigen bevorzugt sprechende Hersteller-/Produktnamen und Rollen
    - z. B. `Bluetooth`, `Speicher`, `Controller`, `Hub`
  - Root-Hubs werden in `Simple` verborgen
  - `mount_ref` zeigt jetzt zusaetzlich Groesseninfo aus dem Storage-Broker-Pfad
    - Quelle / Dateisystem / Groesse / Host-Pfad / Policy
  - die Quelle fuer `mount_ref` ist dabei klar:
    - `runtime-hardware` liest publizierte Commander-Storage-Assets
    - nicht direkt die Live-Diskliste
  - ein echter Folgefehler wurde dabei sichtbar und ist jetzt bereinigt:
    - veraltete publizierte Assets konnten im `Simple`-Wizard weiter als `Speicherpfade` auftauchen
    - obwohl die zugehoerigen Host-Pfade bereits nicht mehr existierten
    - die alten `gaming-station-config`- / `gaming-station-data`-Assets wurden deshalb live entfernt
  - `block_device_ref` ist fuer `Simple` inzwischen staerker gefiltert:
    - `dm-*`, `loop*`, `ram*`, `zram*`, `md*` verborgen
    - kleine Partitionen unter `1 GB` verborgen
    - sichtbar bleiben vor allem grosse, attachbare, nutzerrelevante Partitionen
    - sichtbare grosse Partitionen bekommen jetzt zusaetzlich sprechendere Namen
      - z. B. `Read-only Partition 3`, `Read-only Partition 2`, `Service-Speicher`
- Parallel dazu wurde der Storage-Broker-Befund fuer dieselben Speicherpfade sauberer dokumentiert:
  - `/dev/sdd1` kann jetzt im Teilzustand auftauchen mit
    - `PARTLABEL=games`
    - `label=games`
    - aber noch leerem `filesystem`
  - das ist der Zustand "Partition erfolgreich angelegt, `mkfs` noch nicht erfolgreich"
- dafuer war ein echter Redeploy noetig:
  - erst `jarvis-admin-api` neu bauen
  - danach `runtime-hardware` neu deployen
  - Grund:
    - der `runtime-hardware`-Blueprint baut aus den in `jarvis-admin-api` eingebetteten Quellen
- fuer den aktuellen Arbeitspfad ist jetzt die Detailnotiz `26-Runtime-Hardware-block_device_ref-Implementationsplan` die kanonische Reihenfolge

Explizite Reihenfolge fuer den naechsten `block_device_ref`-Ausbau:

1. zuerst die Vertraege leicht runtime-neutral machen
   - damit `block_apply_candidates` nicht zu container-spezifisch festfrieren
2. danach erst den echten Engine-Adapter fuer Container vorbereiten
   - weiter deaktiviert
   - weiter ohne Auto-Apply
3. danach den vorhandenen Preview-/Deploy-Pfad weiter haerten
   - weitere UI-Vertiefung nur auf Basis der bestehenden `hardware_preview`-/`hardware_deploy`-Payloads
   - kein zweiter Opt-in-Pfad ausserhalb des Deploy-Dialogs

Naechster realer Schritt:

- `container_connector` und die storage-nahe Discovery-/Policy-Schicht nach den ersten Realdaten weiter haerten
- danach die `block_apply_*`-Vertraege und Handoffs noch etwas runtime-neutraler schneiden
- danach erst weitere UI-Integration auf dem bereits vorhandenen Deploy-/Preview-Pfad vertiefen

Live verifiziert:

- `jarvis-admin-api` neu gebaut und gestartet
- Blueprint `runtime-hardware` in der Commander-API vorhanden
- `runtime-hardware` mehrfach erfolgreich neu deployt
- der laufende `runtime-hardware`-Container war dabei jeweils `healthy`
- zusaetzlicher Live-Fix:
  - `GET /api/runtime-hardware/resources?connector=container` konnte trotz gesunder Discovery auf `500` fallen
  - Ursache war ein OSError beim Schreiben von `/app/data/state/last_resources.json.tmp`
  - `runtime_hardware/store.py` schreibt diese Snapshot-Dateien jetzt fehlertolerant
  - `runtime_hardware/api.py` behandelt `last_resources` / `last_plan` / `last_validate` nur noch als optionale State-Snapshots
  - danach wurde `runtime-hardware` erneut neu gestartet; `resources` liefert wieder `200 OK`
- Frontend-Livepfad verifiziert:
  - `jarvis-webui` mountet `adapters/Jarvis/js` und `adapters/Jarvis/static` direkt als Bind-Mount
  - reine Wizard-/CSS-Aenderungen brauchen deshalb keinen eigenen Runtime-Hardware-Redeploy
  - fuer den sichtbaren Effekt reicht im Normalfall Browser-Reload / Hard-Refresh
- API erfolgreich geprueft:
  - `GET /health`
  - `GET /hardware/connectors`
  - `GET /hardware/capabilities`
  - `GET /hardware/resources`
  - `GET /hardware/targets/{type}/{id}/state`
  - `POST /hardware/validate`
  - `POST /hardware/plan`
- zusaetzlich ueber `admin-api` erfolgreich geprueft:
  - `GET /api/runtime-hardware/health`
  - `GET /api/runtime-hardware/connectors`
  - `GET /api/runtime-hardware/capabilities`
  - `GET /api/runtime-hardware/resources`
- zusaetzlich ueber Commander-Blueprint-Pfad erfolgreich geprueft:
  - `GET /api/commander/blueprints/{blueprint_id}/hardware`
  - `POST /api/commander/blueprints/{blueprint_id}/hardware/plan`
  - `POST /api/commander/blueprints/{blueprint_id}/hardware/validate`
  - `POST /api/commander/blueprints/{blueprint_id}/hardware/resolve`
  - Ergebnis gegen echten Demo-Blueprint:
    - `plan.summary = requires_recreate`
    - erste Aktion `stage_for_recreate`
    - `validate.valid = true`
- zusaetzlich im Deploy-Pfad geprueft:
  - aufgeloeste `device_overrides` werden mit expliziten Runtime-Overrides gemerged
  - `block_device_ref` bleibt ohne expliziten Opt-in weiterhin konservativ und erzeugt im Standardfall Review-/Warning-Signale wie `storage_review_required:...`
  - `mount_ref` wird bei explizitem `container_path` in echte `mount_overrides` uebersetzt
  - Live belegt:
    - `/data/services/gaming-station/config -> /mnt/game-config`
    - `deploy_warnings = []`
  - Guard-Pfade live belegt:
    - blockierter Zielpfad `/proc/runtime-hw` -> `supported = false`
    - `policy_state=read_only` + `mode=rw` -> `supported = false`
  - `block_device_ref`-Resolve live belegt:
    - `system_block_device_ref_forbidden:container::block_device_ref::/dev/sda`
    - `block_apply_previews` sichtbar
    - `block_apply_candidates` nur fuer geeignete Kandidaten, aber noch deaktiviert
  - `Simple`-UX live belegt:
    - `Mount Refs` zeigen jetzt Groesseninfo im Sekundaertext
    - `Monitor-Audio` ist aus `Simple` verschwunden
    - Maus-/Absolute-Maus erscheinen als ein gruppierter Eintrag
    - kleine Block-Partitionen wie `16 MB`, `200 MB`, `751 MB` sind in `Simple` verborgen
  - echter Block-Handoff-Deploy live belegt:
    - Container `9b942712fdf1...`
    - `HostConfig.Devices = [{"PathOnHost":"/dev/sdd1","PathInContainer":"/dev/game-disk","CgroupPermissions":"rwm"}]`

Operative Begleitentscheidung waehrend der Umsetzung:

- Commander-Quota fuer Parallelstarts wurde von `3` auf `5` angehoben
- Grund:
  - `runtime-hardware` laeuft jetzt selbst als Systemservice im Stack
  - zusaetzliche Entwicklungs- und Testcontainer sollen den normalen Commander-Flow nicht mehr sofort blockieren
- Live sichtbar im Commander-Dashboard als `3/5`

Wichtige reale Befunde aus dem ersten Deploy:

- der erste Deploy scheiterte an einem Scope-Mismatch:
  - `storage_scope_violation: mount '/sys' is outside scope 'runtime-hardware'`
  - Fix: Paketmanifest und Blueprint-Scope wurden angeglichen
- der zweite Fehler lag im Docker-SDK-Buildpfad des Commander:
  - das Heredoc-`RUN python3 - <<'PY'` wurde im Legacy-Builder nicht sauber materialisiert
  - Fix: Dockerfile-Generator auf klassischen `python3 -c`-Pfad umgestellt

---

## 1. Zielbild

Am Ende soll Jarvis eine eigene Hardware-/Attachment-Schicht haben, die nicht an einen einzelnen Runtime-Typ gebunden ist.

Der Zielstand besteht aus vier Teilen:

1. ein eigener Service `jarvis-runtime-hardware`
2. ein generisches Core-Modell fuer Hardware-Ressourcen, Attachment-Intents und Apply-Plaene
3. austauschbare Connectoren fuer verschiedene Runtime-Typen
4. eine UI, in der Hardware und storage-nahe Referenzen strukturiert ausgewaehlt und auf Blueprints oder laufende Runtime-Ziele angewendet werden koennen

Nicht Ziel des MVP:

- voller QEMU-Hotplug vom ersten Tag an
- allgemeine USB-/PCI-Passthrough-Automation fuer alle Faelle
- Storage-Provisionierung im Hardware-Service selbst
- Ersatz des bestehenden `Container Commander`

---

## 2. Leitprinzipien

## 2.1 Runtime-unabhaengiger Kern

Das Kernmodell darf keine Docker-, Gaming- oder QEMU-Sonderlogik als primare Wahrheit enthalten.

Connectoren liefern nur:

- Inventar
- Capability-Matrix
- Runtime-Ist-Zustand
- Apply-/Detach-Verhalten

## 2.2 Storage bleibt beim Storage Broker

Disks, Mounts und storage-nahe Ressourcen duerfen im `runtime_hardware`-Modul nur als Referenzen modelliert werden.

Das Modul darf:

- `mount_ref`
- `block_device_ref`
- storage-bezogene Zielpolicy

kennen, aber nicht selbst provisionieren oder materialisieren.

## 2.3 Live-Aenderungen ehrlich modellieren

Nicht jede Runtime kann echte Live-Injektion.

Deshalb muss jede Aktion formal in eine dieser Klassen fallen:

- `live_attach`
- `live_detach`
- `stage_for_recreate`
- `unsupported`

## 2.4 Ein UX-Muster fuer mehrere Backends

Die UI fuer Hardware-Auswahl und Runtime-Hardware-Setup soll spaeter fuer `container`, `qemu` und weitere Connectoren wiederverwendbar sein.

---

## 3. Verantwortungsgrenzen

Verantwortung von `jarvis-runtime-hardware`:

- Hardware-/Resource-Discovery
- normierte Darstellung verfuegbarer Ressourcen
- Capability-Bewertung pro Connector
- Plan-Erzeugung fuer Attach/Detach/Validate
- Audit-/Job-Status fuer Hardware-Aenderungen

Keine Verantwortung:

- keine Blueprint-CRUD-Hauptlogik
- keine Storage-Provisionierung
- keine Ersatz-Engine fuer Container-Lifecycle
- keine Gaming-Sonderorchestrierung

Verantwortung von `Container Commander` bleibt:

- Blueprints verwalten
- Container deployen/starten/stoppen
- Runtime-Overrides anwenden
- bestehende Approval-/Trust-/Policy-Pfade erzwingen

Verantwortung des `Storage Broker` bleibt:

- Volumes/Mount-Targets inventarisieren
- Storage provisionieren
- mountbare/storage-bezogene Referenzen aufloesen

---

## 4. Service-Schnitt

Neuer Service:

- Name: `jarvis-runtime-hardware`
- Rolle: eigener interner API-Service / eigener Container
- erste Integrationsrichtung: ueber `admin-api` als Gateway

Empfohlene innere Schichten:

1. `runtime_hardware/models`
2. `runtime_hardware/connectors`
3. `runtime_hardware/planner`
4. `runtime_hardware/jobs`
5. `runtime_hardware/api`
6. `runtime_hardware/store`

Empfohlene erste Connectoren:

1. `container_connector`
2. `qemu_connector` als vorbereiteter Stub
3. `remote_agent_connector` spaeter

---

## 5. Domaaenenmodell

## 5.1 HardwareResource

Reprasentiert eine attachbare oder referenzierbare Ressource.

Felder:

- `id`
- `kind`
- `source_connector`
- `label`
- `host_path`
- `vendor`
- `product`
- `serial`
- `capabilities`
- `risk_level`
- `availability_state`
- `metadata`

Erste `kind`-Klassen:

- `input`
- `usb`
- `device`
- `gpu_access`
- `block_device_ref`
- `mount_ref`

## 5.2 AttachmentIntent

Beschreibt die gewuenschte Zuordnung einer Ressource.

Felder:

- `resource_id`
- `target_type`
- `target_id`
- `attachment_mode`
- `policy`
- `requested_by`

## 5.3 AttachmentPlan

Beschreibt den konkreten Umsetzungsplan.

Felder:

- `target`
- `connector`
- `actions`
- `requires_approval`
- `requires_restart`
- `validation_steps`
- `rollback_hint`

Moegliche Aktionen:

- `live_attach`
- `live_detach`
- `stage_for_recreate`
- `reject`

## 5.4 RuntimeCapability

Beschreibt pro Connector und Ressourcentyp, was moeglich ist.

Felder:

- `resource_kind`
- `discover`
- `attach_live`
- `detach_live`
- `stage_supported`
- `requires_privileged`
- `requires_restart`
- `notes`

## 5.5 AttachmentState

Beschreibt den aktuellen Ist-Zustand an einem Runtime-Ziel.

Felder:

- `target_type`
- `target_id`
- `attached_resources`
- `staged_resources`
- `validation_state`
- `last_applied_at`

---

## 6. Connector-Interface

Jeder Connector muss dieselbe Grundschnittstelle liefern:

- `discover_resources()`
- `get_capabilities()`
- `discover_target_state(target_type, target_id)`
- `plan_apply(intents, target)`
- `apply(plan)`
- `detach(plan)`
- `validate(target_type, target_id)`
- `explain_unsupported(intent, target)`

Wichtig:

- Connectoren speichern keine Blueprint-Wahrheit.
- Connectoren sollen keine globale eigene Konfiguration etablieren.
- Connectoren duerfen nur Runtime-spezifisches Verhalten kapseln.

---

## 7. Integration in bestehende Jarvis-Komponenten

## 7.1 Admin API

`admin-api` bleibt das Frontdoor-Gateway fuer die UI.

Betroffene spaetere Integrationspunkte:

- `adapters/admin-api/commander_routes.py`
- optional neue Proxy-/Gateway-Route fuer `runtime_hardware`
- Zusammenfuehrung mit bestehendem Deploy-/Blueprint-Flow

Status jetzt:

- der allgemeine Gateway-Pfad ist umgesetzt
- der Commander-Blueprint-Pfad fuer `hardware_intents` ist umgesetzt
- die UI ist jetzt in einem ersten Schritt angeschlossen
  - `Simple`-Wizard fuer strukturierte Auswahl
  - read-only `Hardware Preview` im Blueprint-Editor
  - echter Deploy-Opt-in im Deploy-Dialog ist umgesetzt
  - der Editor bleibt bewusst ohne eigenen lokalen Opt-in

## 7.2 Container Commander

`Container Commander` wird nicht ersetzt, sondern erweitert.

Betroffene spaetere Integrationspunkte:

- `container_commander/engine.py`
- `container_commander/engine_runtime_blueprint.py`
- `container_commander/blueprint_store.py`

Wahrscheinliche Erweiterungen:

- strukturierte `hardware_intents` im Blueprint
- Aufloesung von `hardware_intents` in `device_overrides`
- Aufloesung von `mount_ref`/`block_device_ref` ueber den `Storage Broker`

## 7.3 Storage Broker

Der `Storage Broker` bleibt allein zustaendig fuer Storage-Materialisierung.

Der Hardware-Service darf nur:

- Storage-Ressourcen referenzieren
- Capability-/Policy-Kontext ausweisen
- Apply-Plaene fuer mount-/disk-nahe Referenzen an den Broker andocken

## 7.4 Frontend

Erste wahrscheinliche UI-Integrationspunkte:

- `adapters/Jarvis/js/apps/terminal/blueprint-editor.js`
- `adapters/Jarvis/js/apps/terminal/preflight.js`
- Container-Detail-UI unter `adapters/Jarvis/js/apps/terminal/`
- optional spaeter eigene Hardware-Admin-Ansicht analog `storage-broker.js`

---

## 8. API-Plan fuer `jarvis-runtime-hardware`

Empfohlene erste Endpunkte:

- `GET /hardware/resources`
- `GET /hardware/resources/{id}`
- `GET /hardware/connectors`
- `GET /hardware/capabilities`
- `GET /hardware/targets/{type}/{id}/state`
- `POST /hardware/plan`
- `POST /hardware/apply`
- `POST /hardware/detach`
- `POST /hardware/validate`

Optional spaeter:

- `GET /hardware/jobs`
- `GET /hardware/jobs/{id}`
- `POST /hardware/discover/refresh`

Antworten sollten immer klar enthalten:

- `supported`
- `requires_restart`
- `requires_approval`
- `risk_level`
- `connector`
- `explanation`

---

## 9. Blueprint- und Runtime-UX

## 9.1 Blueprint Create/Edit

Im Blueprint-Editor soll ein neuer Bereich `Hardware` entstehen.

Dort soll der Nutzer:

- verfuegbare Hardware sehen
- nach `Input`, `USB`, `Devices`, `Storage refs` filtern
- Ressourcen per Klick auswaehlen
- sehen, ob die Ziel-Runtime diese spaeter live oder nur per Recreate anwenden kann

Wichtig fuer den Uebergang:

- rohe Textfelder fuer `Devices` und `Mounts` vorerst parallel behalten
- neue strukturierte `hardware_intents` schrittweise zum kanonischen Pfad machen

## 9.2 Container Detail

Im Container-Detail soll ein zweites Tab `Hardware Setup` entstehen.

Es zeigt:

- aktuell attachte Ressourcen
- verfuegbare zusaetzliche Ressourcen
- Status `live supported`
- Status `requires restart`
- Status `unsafe / privileged`

Moegliche Aktionen:

- `Attach now`
- `Stage for restart`
- `Detach`
- `Validate`

## 9.3 Zukunftspfad fuer QEMU

Dieselbe UI bleibt bestehen.

Nur der Connector und die Capabilities aendern sich.

Damit wird spaeter eine eigene QEMU-Weboberflaeche moeglich, ohne das UI- oder Datenmodell neu zu erfinden.

---

## 10. Implementationsphasen

## Phase 0: Architektur- und Vertragsfestlegung

Ziel:

- Name, Grenzen, API-Vertrag und Domaaenenmodell finalisieren

Arbeitspakete:

1. Service-Name und Repo-Ort festlegen
2. Connector-Interface definieren
3. Ressourcenklassen und Capability-Matrix festlegen
4. Grenze zu `Storage Broker` und `Container Commander` dokumentieren
5. API-Shape und JSON-Modelle festschreiben

Akzeptanzkriterien:

- eindeutiger Architekturentscheid dokumentiert
- keine Ueberschneidung der Verantwortlichkeiten offen
- MVP-Umfang klar abgegrenzt

## Phase 1: Service-Grundgeruest

Ziel:

- eigener Container/Service steht und liefert Dummy- oder Basisantworten

Arbeitspakete:

1. Service-Skelett anlegen
2. internes Store-/Job-Modell anlegen
3. API-Routen fuer Discovery, Plan, State, Validate anlegen
4. Health-/Readiness-Pfad anlegen

Akzeptanzkriterien:

- Service laeuft als eigener Container
- API ist ueber `admin-api` oder direkt erreichbar
- leere/basisnahe Antworten folgen bereits dem finalen Datenmodell

Status 2026-03-27:

- Service-Skelett, API, Modelle, Planner und `container_connector`-Grundgeruest sind im Repo vorhanden
- der echte Deploy-/Startup-Test ist inzwischen erfolgreich durchgelaufen
- der naechste Schritt ist jetzt nicht mehr Grundaufbau oder Gateway, sondern Haertung des `container_connector` und weitere Vertiefung des `block_device_ref`-Pfads

## Phase 2: Container-Connector v1

Ziel:

- erste echte Discovery- und Capability-Schicht fuer Container

Arbeitspakete:

1. Host-/Runtime-nahe Ressourcen inventarisieren
2. Input-/USB-/Device-/GPU-nahe Klassen normieren
3. Ist-Zustand laufender Container lesbar machen
4. ehrliche Capability-Matrix fuer Container definieren

Akzeptanzkriterien:

- UI/API sehen reale Ressourcen
- Container-Ziele liefern reale Attachment-State-Daten
- unsupported/live/recreate ist pro Ressource nachvollziehbar

## Phase 3: Plan-Engine

Ziel:

- aus `AttachmentIntent` wird ein formaler `AttachmentPlan`

Arbeitspakete:

1. Plan-Regeln fuer `live_attach`, `stage_for_recreate`, `reject`
2. Risiko-/Approval-Markierung
3. Validation- und Rollback-Hinweise
4. normalize/merge von Mehrfach-Intents

Akzeptanzkriterien:

- derselbe Intent erzeugt deterministische Plaene
- Risk/Approval/Restart ist maschinenlesbar

## Phase 4: Storage-Broker-Anbindung

Ziel:

- storage-nahe Referenzen sauber andocken, ohne Storage-Wissen zu duplizieren

Arbeitspakete:

1. `mount_ref` und `block_device_ref` definieren
2. Referenzaufloesung ueber `Storage Broker`
3. Plan-Regeln fuer storage-bezogene Attachments
4. Fehlerfaelle fuer fehlende Broker-Ressourcen behandeln

Akzeptanzkriterien:

- keine doppelte Storage-Logik im Hardware-Service
- storage-nahe Plaene referenzieren Broker-Ressourcen sauber

## Phase 5: Blueprint-Integration

Ziel:

- Blueprints koennen strukturierte Hardware-Intents speichern

Arbeitspakete:

1. Blueprint-Schema um `hardware_intents` erweitern
2. Migrations-/Kompatibilitaetspfad fuer rohe `devices`/`mounts`
3. Deploy-Pfad von Intent -> Plan -> Runtime-Override
4. Validierung beim Blueprint-Speichern

Akzeptanzkriterien:

- Blueprints koennen strukturierte Hardware-Konfiguration tragen
- bestehende Blueprints bleiben kompatibel

## Phase 6: UI v1

Ziel:

- Hardware im Blueprint-Flow und im Container-Detail bedienbar machen

Arbeitspakete:

1. `Hardware`-Bereich im Blueprint-Editor
2. `Hardware Setup`-Tab im Container-Detail
3. Capability-/Risk-Badges
4. Plan-Vorschau vor Apply

Akzeptanzkriterien:

- Nutzer kann Ressourcen sichtbar auswaehlen
- UI unterscheidet klar zwischen `live` und `requires restart`

## Phase 7: Apply-/Detach-Jobs

Ziel:

- kontrollierte Ausfuehrung mit Status, Audit und Fehlerrueckmeldung

Arbeitspakete:

1. Job-Queue oder einfacher Apply-Runner
2. Status-/Log-Modell
3. Fehler-/Rollback-Hinweise
4. Validate nach Apply

Akzeptanzkriterien:

- Hardware-Aenderungen sind nachvollziehbar
- Fehler koennen klar auf Connector, Ressource oder Policy zurueckgefuehrt werden

## Phase 8: QEMU-Connector vorbereiten

Ziel:

- Datenmodell gegen einen zweiten Runtime-Typ absichern

Arbeitspakete:

1. `qemu_connector`-Stub mit Capability-Matrix
2. Abgleich des Modells gegen typische QEMU-/libvirt-Ressourcen
3. Verifikation, dass keine Container-Spezifika ins Core-Modell leaken

Akzeptanzkriterien:

- das Core-Modell bleibt connector-neutral
- QEMU kann spaeter ohne Grossumbau andocken

---

## 11. Risiken und Architekturfallen

1. Das Modul darf nicht heimlich zum zweiten `Container Commander` werden.
2. Das Modul darf keine eigene Storage-Materialisierung aufbauen.
3. `live attach` fuer Container darf nicht versprochen werden, wo technisch nur Recreate sauber ist.
4. Connectoren duerfen nicht jeweils ihre eigene Datenwahrheit ueber Blueprints speichern.
5. Das Datenmodell darf nicht an Docker-Geraete-Strings festkleben, wenn spaeter QEMU und Remote-Agenten kommen sollen.

---

## 12. Empfohlene MVP-Grenze

Der erste ernsthafte MVP sollte nur Folgendes garantieren:

- eigener Hardware-Service laeuft
- `container_connector` liefert reales Inventar
- `hardware_intents` koennen strukturiert gespeichert werden
- UI kann Hardware-Ressourcen sichtbar auswaehlen
- Plan-Engine markiert korrekt `live` vs. `requires restart`
- storage-nahe Referenzen laufen ueber den `Storage Broker`

Nicht Teil dieses MVP:

- vollwertige QEMU-UI
- Remote-Fleet-Hardware ueber mehrere Agents
- komplexe Host-Passthrough-Automation fuer Sonderfaelle

---

## 13. Empfohlene Reihenfolge fuer die reale Umsetzung

1. Architekturvertrag und API-Schema festziehen
2. neuen Service `jarvis-runtime-hardware` anlegen
3. `container_connector` und Capability-Matrix bauen
4. Storage-Broker-Grenze und Referenzmodell festziehen
5. Blueprint-Schema um `hardware_intents` erweitern
6. UI fuer Blueprint-Editor und `Hardware Setup`-Tab bauen
7. Apply-/Detach-Jobs nachziehen
8. erst danach `qemu_connector` vorbereiten

Kurzform:

- zuerst Modell
- dann Container-MVP
- dann UI
- dann QEMU
