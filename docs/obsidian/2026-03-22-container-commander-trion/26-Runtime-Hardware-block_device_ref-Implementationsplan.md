# Runtime Hardware block_device_ref Implementationsplan

Erstellt am: 2026-03-26

Bezug:

- [[23-Runtime-Hardware-Modul-Implementationsplan]]
- [[24-Runtime-Hardware-v0-Installationsvertrag]]
- [[25-Runtime-Hardware-v0-Containerbauplan]]

## Zweck dieser Notiz

Diese Notiz beschreibt den naechsten Ausbau fuer `block_device_ref` im neuen `runtime-hardware`-Pfad.

Fokus dieser Notiz:

- wo welcher Teil eingebaut werden soll
- wann neue Module sinnvoll sind
- wie der `block_device_ref`-Pfad ohne neue Code-Monolithen aufgebaut wird
- welche Phasen fuer Container heute und QEMU spaeter sinnvoll sind

Wichtig:

- Das Ziel ist **nicht** sofortiges blindes Block-Device-Passthrough.
- Zuerst kommt ein sauberer Policy-, Preview- und Resolution-Pfad.
- Materialisierung darf erst spaeter und nur unter klaren Guards folgen.

## Status 2026-03-27

Phase 1 ist umgesetzt, grosse Teile von Phase 2 und der Materialisierungsvorbereitung sind ebenfalls bereits real vorhanden:

- `container_commander/hardware_block_resolution.py` existiert als eigenes Modul fuer `block_device_ref`
- `container_commander/hardware_block_apply.py` existiert als eigenes Modul fuer strukturierte `block_apply_previews`
- `container_commander/hardware_block_apply_plan.py` existiert als eigenes Modul fuer spaetere, heute noch deaktivierte `block_apply_candidates`
- `container_commander/hardware_block_container_adapter.py` existiert als eigenes Modul fuer spaetere, heute noch deaktivierte Container-Adapterplaene
- `container_commander/hardware_resolution.py` dispatcht fuer `block_device_ref` bereits in dieses Modul
- `adapters/runtime-hardware/runtime_hardware/connectors/container_storage_discovery.py` kapselt jetzt Storage-Broker- und Storage-Asset-Discovery ausserhalb von `container_connector.py`
- `runtime-hardware` liefert im `plan` jetzt zusaetzliche Ressourcen-Metadaten mit:
  - `host_path`
  - `risk_level`
  - `capabilities`
  - `resource_metadata`

Aktive Regeln im ersten Live-Stand:

- `zone=system` / `is_system=true` -> blockiert
- `policy_state=blocked` -> blockiert
- `policy_state=read_only` + `policy.mode=rw` -> blockiert
- `allowed_operations` ohne `assign_to_container` -> blockiert
- `disk_type=disk` bleibt weiter review-only und erzeugt Zusatzwarnung

Live belegt am 2026-03-26:

- `runtime-hardware` liefert fuer `container::block_device_ref::/dev/sda` Broker-Metadaten mit `zone=system`, `policy_state=blocked`, `is_system=true`
- `POST /api/commander/blueprints/{id}/hardware/resolve` loest denselben Pfad jetzt zu
  - `supported=false`
  - `unresolved_resource_ids=["container::block_device_ref::/dev/sda"]`
  - Warning `system_block_device_ref_forbidden:container::block_device_ref::/dev/sda`
- `resolve` liefert jetzt zusaetzlich:
  - `block_apply_previews`
  - `block_apply_candidates`
- `block_apply_previews` sind inzwischen leicht runtime-neutral gehaertet:
  - `target_runtime`
  - `target_runtime_path`
  - `candidate_runtime_binding`
  - container-spezifische Details nur unter `runtime_parameters.container`
- Kandidaten bleiben aktuell bewusst deaktiviert:
  - `activation_state=disabled_until_engine_support`
  - `activation_reason=future_engine_block_apply_enablement`
- `resolve` liefert jetzt zusaetzlich vorbereitete, aber weiter deaktivierte `block_apply_container_plans`
- `resolve` liefert jetzt zusaetzlich vorbereitete, aber weiter deaktivierte `block_apply_engine_handoffs`
- `start_container()` hat jetzt einen ersten expliziten Opt-in fuer diese Handoffs:
  - `block_apply_handoff_resource_ids`
  - nur explizit selektierte Resource-IDs werden uebernommen
  - Approval-/Resume-Pfade transportieren den Wert weiter
- der Read-/Preview-Pfad spiegelt den Opt-in jetzt sichtbar:
  - `block_apply_handoff_resource_ids_hint`
  - `engine_opt_in_available`
  - `resolution_preview`
- der Frontend-Pfad fuer den echten Opt-in ist inzwischen real angeschlossen:
  - `adapters/Jarvis/js/apps/terminal/preflight.js`
  - Auswahl im Deploy-Dialog
  - Versand von `block_apply_handoff_resource_ids`
  - Rueckmeldung `requested` vs `applied`
- der erste Frontend-Pfad dafuer ist jetzt sichtbar, aber bewusst noch read-only:
  - `Hardware Preview` im Blueprint-Editor zeigt die Opt-in-faehigen Handoffs nur als Vorschau
  - keine lokale Checkbox-Auswahl mehr im Editor
  - der echte Benutzer-Opt-in passiert jetzt ausschliesslich im Deploy-Dialog
- der Deploy-Response spiegelt den Opt-in jetzt sichtbar:
  - `block_apply_handoff_resource_ids_requested`
  - `block_apply_handoff_resource_ids_applied`
  - `hardware_resolution_preview`
- der Commander-Deploy-Pfad nutzt fuer `block_device_ref`-Resolution im `admin-api`-/Container-Kontext jetzt lokal eingebettete `runtime-hardware`-Module bevorzugt
  - Grund:
    - der HTTP-Pfad zu `runtime-hardware` war im echten Deploy ueber Host-/Gateway-Fallbacks operativ zu langsam bzw. unzuverlaessig
  - die lokale Deploy-Resolution bleibt dabei nicht losgeloest:
    - Storage-Broker-Metadaten kommen weiter direkt vom `storage-broker`
    - Storage-Assets kommen lokal aus `container_commander.storage_assets`
  - der allgemeine `runtime-hardware`-Service/Gateway bleibt fuer Inventory und API weiter erhalten
- live verifiziert: bei Whole-Disk-Review-Faellen bleiben
  - `block_apply_candidates=[]`
  - `block_apply_container_plans=[]`
  - `block_apply_engine_handoffs=[]`
- live verifiziert: bei der erlaubten Partition `container::block_device_ref::/dev/sdd1` liefert derselbe Resolve-Pfad jetzt
  - `supported=true`
  - `block_apply_candidate` vorhanden
  - `block_apply_container_plan` vorhanden
  - `block_apply_engine_handoff` vorhanden
  - Binding `/dev/sdd1:/dev/game-disk`
  - weiter deaktiviert, weiter ohne Auto-Apply
- zusaetzlich live verifiziert im echten End-to-End-Deploy:
  - `POST /api/commander/containers/deploy`
  - `block_apply_handoff_resource_ids_requested=["container::block_device_ref::/dev/sdd1"]`
  - `block_apply_handoff_resource_ids_applied=["container::block_device_ref::/dev/sdd1"]`
  - Docker-Inspect:
    - `HostConfig.Devices = [{"PathOnHost":"/dev/sdd1","PathInContainer":"/dev/game-disk","CgroupPermissions":"rwm"}]`
  - Commander-Deploy-Laufzeit:
    - vorher ca. `37s`
    - danach ca. `0.3s`
- der `runtime-hardware`-Blueprint embedet jetzt auch `container_storage_discovery.py`; der fehlende Embed-Pfad war zwischenzeitlich ein echter Laufzeitfehler und ist jetzt per Contract-Test abgesichert
- fuer die Docker-spezifische `Simple`-UX gilt zusaetzlich jetzt:
  - technische Block-Devices wie `dm-*`, `loop*`, `ram*`, `zram*`, `md*` werden verborgen
  - kleine Partitionen unter `1 GB` werden in `Simple` verborgen
  - sichtbar bleiben vor allem grosse, attachbare Partitionen
  - `block_device_ref` bleibt damit fuer normale Nutzer nutzbar, ohne die technische Vollsicht zu verlieren
- die frontendseitige Darstellung dafuer ist inzwischen ebenfalls nachgeschaerft:
  - `block_device_ref` erscheint im Wizard unter `Direkte Datentraeger`
  - die Auswahl erfolgt als Karte statt als rohe Checkbox-Zeile
  - `NAS/Storage`-Preset ist vorhanden
  - `NAS/Storage`-Preset ist inzwischen enger gefiltert
    - nicht mehr pauschal alle grossen Partitionen
    - sondern nur noch zuweisbare Storage-Kandidaten
  - direkte Datentraeger bleiben klar von `Speicherpfaden` / `mount_ref` getrennt
  - Klartext-Hinweis direkt an der Karte:
    - direktes Block-Device nur noetig, wenn die App das Geraet selbst sehen muss
  - sichtbare grosse Partitionen bekommen jetzt zusaetzlich sprechendere Anzeigenamen
    - z. B. `Read-only Partition 3`, `Read-only Partition 2`, `Service-Speicher`

Verbindliche Reihenfolge fuer den naechsten Ausbau:

1. zuerst die Vertraege leicht runtime-neutral machen
   - damit `block_apply_candidates` nicht zu container-spezifisch festfrieren
2. danach erst den echten Container-Engine-Adapter vorbereiten
   - weiter deaktiviert
   - weiter ohne Auto-Apply
3. danach den vorhandenen Preview-/Deploy-Vertrag weiter haerten
   - weiter entlang von `resolution_preview` und `hardware_deploy.*`
   - kein zweiter lokaler Opt-in-Pfad ausserhalb des Deploy-Dialogs

Restoffen nach dem Feinschnitt vom 2026-03-27:

- sichtbar gebliebene grosse Partitionen sollten noch sprechendere Labels bekommen
  - statt nur `sdb3`, `sdc2`, `sdd1`
- die `Simple`-UI sollte `block_device_ref` kuenftig eher als "Direkte Datentraeger" kommunizieren
- kleine technische Partitionen sollen verborgen bleiben; Expertenansicht darf sie weiter zeigen

---

## 1. Zielbild fuer block_device_ref

`block_device_ref` soll im System als eigenstaendige, policy-kontrollierte Ressourcenklasse existieren.

Das bedeutet:

- `runtime-hardware` inventarisiert Block-Devices aus dem Storage-Broker-Pfad
- `Container Commander` speichert den Wunsch weiterhin nur als `hardware_intent`
- der Resolver bewertet:
  - erlaubt
  - nur mit Approval
  - nur `stage_for_recreate`
  - verboten
- Container bleiben zunaechst konservativ
- QEMU soll spaeter denselben Ressourcentyp wiederverwenden koennen

Kurz:

- heute zuerst Preview/Policy
- spaeter kontrollierte Materialisierung
- keine Sonderlogik direkt in `engine.py`

---

## 2. Grundregel fuer den Modulzuschnitt

Der `block_device_ref`-Pfad darf **nicht** als weitere Sammellogik in bestehende grosse Dateien geklebt werden.

Nicht weiter aufblaehen:

- `container_commander/engine.py`
- `container_commander/hardware_resolution.py`
- `adapters/runtime-hardware/runtime_hardware/connectors/container_connector.py`

Stattdessen:

- neue Verantwortung bekommt neue Datei
- Policy, Resolution und Materialisierung bleiben getrennt
- Preview und Deploy muessen denselben Resolver benutzen

---

## 3. Empfohlener Modulzuschnitt

## 3.1 Runtime-Hardware-Seite

Bestehender Ort:

- `adapters/runtime-hardware/runtime_hardware/connectors/container_connector.py`

Aktueller Zustand:

- Discovery fuer `block_device_ref` ist bereits vorhanden
- Broker-Metadaten wie `zone`, `policy_state`, `allowed_operations`, `is_system` liegen bereits an

Aktueller Split / naechster Rest-Split:

1. `adapters/runtime-hardware/runtime_hardware/connectors/container_storage_discovery.py`
   Status:
   - bereits angelegt
   Verantwortung:
   - Broker-Disks laden
   - `block_device_ref`-Ressourcen normalisieren
   - spaeter optional auch Mount- und Asset-Helfer kapseln

2. `adapters/runtime-hardware/runtime_hardware/connectors/container_storage_policy.py`
   Naechster sinnvoller Split:
   - Hilfsfunktionen fuer Broker-Metadaten
   - Ableitung von Capability-Hinweisen
   - Einordnung:
     - `system`
     - `blocked`
     - `read_only`
     - `managed_rw`
     - `disk` vs `partition`

Wann lohnt sich der Rest-Split:

- jetzt, sobald weitere Broker-/Policy-Heuristiken dazukommen
- nicht erst wenn `container_connector.py` wieder Richtung 500+ Zeilen kippt

Warum:

- `container_connector.py` soll Runtime-Connector bleiben, nicht Discovery-Monolith
- `container_storage_discovery.py` existiert bereits und bildet die saubere Basis fuer den Policy-Split

## 3.2 Commander-Seite

Bestehender Ort:

- `container_commander/hardware_resolution.py`

Aktueller Zustand:

- Device- und Mount-Aufloesung liegen schon dort
- `block_device_ref` hat inzwischen einen getrennten Policy-, Preview- und expliziten Handoff-Pfad

Aktueller Split / Guardrail:

1. `container_commander/hardware_block_resolution.py`
   Status:
   - bereits angelegt
   Verantwortung:
   - nur `block_device_ref`
   - Policy-Entscheidung
   - Approval-Markierung
   - Preview-Resultate
   - spaeter optionale Materialisierungsvorbereitung

2. `container_commander/hardware_resolution.py`
   Status jetzt:
   - dispatcht bereits fuer `block_device_ref` in das Spezialmodul
   soll dauerhaft nur noch:
   - gemeinsame Orchestrierung
   - Dispatch zu `device` / `mount` / `block`
   - Merge-Helfer
   enthalten

Wann ist der Split ausreichend gezogen:

- jetzt, solange neue `block_device_ref`-Regeln nur noch im Spezialmodul landen
- nicht erst wenn `hardware_resolution.py` wieder fachliche Speziallogik aufsammelt

Warum:

- `mount_ref` und `block_device_ref` haben unterschiedliche Sicherheitsregeln
- derselbe Resolver-Dateiklotz wuerde schnell wieder unlesbar

## 3.3 Spaetere Materialisierung

Wenn ueberhaupt Container-Materialisierung kommt, dann nicht in `hardware_block_resolution.py`, sondern getrennt:

- `container_commander/hardware_block_apply.py`

Verantwortung:

- nur vorbereitete Umsetzungsdaten bauen
- keine Policy-Entscheidung
- keine HTTP-/Broker-Discovery

Das verhindert, dass Preview, Policy und Apply wieder in einem Modul landen.

---

## 4. Phasenplan

## Phase 1: Block-Policy sauber machen

Ziel:

- `block_device_ref` bekommt klare Resolution-Regeln

Stand jetzt:

- umgesetzt

Einbauorte:

- neu:
  - `container_commander/hardware_block_resolution.py`
- klein angepasst:
  - `container_commander/hardware_resolution.py`
  - `adapters/admin-api/commander_api/hardware.py`

Regeln in Phase 1:

- `zone=system` -> immer blockiert
- `policy_state=blocked` -> immer blockiert
- ganze Disks konservativer behandeln als Partitionen
- `read_only` vs `managed_rw` als eigene Zustandsklasse markieren
- `allowed_operations` aus dem Broker mit auswerten

Erwartetes Resultat:

- `resolve` gibt nicht nur `storage_review_required`, sondern klare, spezifische Gruende zurueck

## Phase 2: Preview und Approval-Semantik haerten

Ziel:

- `resolve`, `plan`, `validate` und spaeter Deploy benutzen dieselbe Wahrheit

Stand jetzt:

- weitgehend umgesetzt
- Preview, Handoffs und Deploy-Opt-in sind sichtbar

Einbauorte:

- `container_commander/hardware_block_resolution.py`
- `adapters/admin-api/commander_api/hardware.py`

Regeln in Phase 2:

- `supported=false` fuer harte Verbote
- `requires_approval=true` fuer riskante, aber prinzipiell zulaessige Faelle
- `requires_restart=true` fuer Container standardmaessig

Wichtig:

- noch keine automatische Uebernahme in `device_overrides`

## Phase 3: Materialisierungsvorbereitung fuer Container

Ziel:

- sauber definieren, welche `block_device_ref`-Faelle im Container ueberhaupt in Frage kommen

Stand jetzt:

- vorbereitet und fuer explizite Handoffs bereits nutzbar
- weiter bewusst ohne Auto-Apply

Einbauorte:

- neu:
  - `container_commander/hardware_block_apply.py`
- klein angepasst:
  - `container_commander/engine.py`

Konservativer Start:

- nur bestimmte Partitionen, nicht ganze System-nahe Disks
- nur bei expliziter Approval-/Policy-Freigabe
- nur `stage_for_recreate`

Wichtig:

- Container-Pfad ist nicht der Haupttreiber
- keine Abkuerzung nur fuer Docker bauen

## Phase 4: QEMU-vorbereiteter Vertrag

Ziel:

- `block_device_ref` so modellieren, dass QEMU spaeter nativer andocken kann

Einbauorte:

- spaeter im Runtime-Hardware-Service:
  - `adapters/runtime-hardware/runtime_hardware/connectors/qemu_storage_discovery.py`
  - `adapters/runtime-hardware/runtime_hardware/connectors/qemu_connector.py`

Der Kernpunkt:

- dieselbe Ressource bleibt `block_device_ref`
- nur Connector und Apply-Pfad unterscheiden sich

---

## 5. Konkrete Anti-Monolith-Regeln

Diese Regeln sollen fuer den Ausbau aktiv gelten:

1. Keine neue Ressourcenklasse komplett in `engine.py`.
   `engine.py` darf nur orchestrieren und gemergte Ergebnisse anwenden.

2. Keine neue Ressourcenklasse komplett in `container_connector.py`.
   Discovery-Helfer muessen aus dem Connector herausgezogen werden, sobald Policy- oder Brokerlogik dazukommt.

3. Keine Datei mit drei Rollen zugleich.
   Eine Datei darf nicht gleichzeitig:
   - Discovery
   - Policy
   - Apply
   machen.

4. Sobald ein Modul ueber etwa 250-350 sinnvolle Zeilen hinauswächst und mehrere Verantwortungstypen enthält, wird gesplittet.

5. Preview und Deploy muessen dieselbe Resolution-Funktion nutzen.
   Keine zweite Wahrheit in Route und Engine.

6. `block_device_ref` und `mount_ref` nie wieder in denselben Spezialpfad zurückfalten.
   Beide kommen aus Storage-Kontext, aber ihre Runtime-Risiken sind verschieden.

---

## 6. Empfohlene naechste konkrete Arbeitspakete

1. `block_apply_*`-Vertraege weiter runtime-neutral schneiden
   Inhalt:
   - `block_apply_candidates` nicht auf Container-Semantik festfrieren
   - container-spezifische Details weiter unter `runtime_parameters.container` halten

2. `adapters/runtime-hardware/runtime_hardware/connectors/container_storage_policy.py` als naechsten Split pruefen
   Inhalt:
   - Broker-Metadaten-Helfer
   - Policy-Zustandsableitungen
   - Trennung von Connector- und Policy-Logik

3. den Container-Engine-Adapter weiter vorbereiten
   Inhalt:
   - weiter deaktiviert
   - weiter ohne Auto-Apply
   - nur explizite Handoff-Uebernahme sauber halten

4. Preview-/Deploy-Readmodell weiter schaerfen
   Inhalt:
   - `resolution_preview`
   - `block_apply_handoff_resource_ids_hint`
   - `hardware_deploy.*`
   konsistent halten

5. Erst danach entscheiden:
   - ob weitere Container-Faelle ueber expliziten Handoff hinaus zulaessig sind
   - oder ob der Pfad fuer Container bewusst eng bleibt und QEMU zuerst profitiert

---

## 7. Entscheidungsregel fuer neue Module

Neue Module sollen **nicht erst dann** entstehen, wenn es schon chaotisch ist.

Ein neuer Split ist sofort faellig, wenn mindestens zwei dieser Punkte zutreffen:

- neue externe Datenquelle kommt dazu
- eigene Sicherheits-/Policy-Regeln entstehen
- Preview und Apply unterscheiden sich fachlich
- QEMU-Wiederverwendung ist spaeter wahrscheinlich
- Datei wuerde sonst zweite oder dritte Verantwortung bekommen

Beim `block_device_ref`-Pfad treffen diese Punkte bereits jetzt zu.

Deshalb ist die richtige Entscheidung:

- ja, neue Module jetzt
- nein, kein weiterer Sammelblock in `hardware_resolution.py` oder `container_connector.py`

---

## 8. Kurzfazit

Der `block_device_ref`-Pfad sollte ab hier in drei Schichten wachsen:

1. Discovery
2. Policy/Resolution
3. spaeter optional Apply

Wenn wir diese Trennung jetzt sauber halten, bleibt der Containerpfad beherrschbar und der spaetere QEMU-Pfad muss nicht wieder aus einem Docker-zentrierten Monolithen herausgeschnitten werden.
