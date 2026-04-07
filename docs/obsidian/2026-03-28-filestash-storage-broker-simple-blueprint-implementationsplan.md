# Filestash als Referenzdienst — Storage-Broker + Simple-Blueprint-Implementationsplan

Stand: 2026-03-28
Status: Kernpfad live belegt

## Ziel

`Filestash` soll als bewusst einfacher Referenzdienst dienen, um den generischen Produktpfad zwischen

- `storage-broker`
- `runtime-hardware`
- Simple Blueprint
- Commander-Deploy
- Docker-Bind-Mounts

sauber zu schliessen, ohne `gaming-station` weiter anzufassen.

Der Zweck ist nicht primaer "ein neuer Dateimanager", sondern ein realistischer Storage-zentrierter Testdienst, mit dem der Standardpfad fuer freigegebene Datentraeger produktreif gemacht werden kann.

---

## Warum Filestash

`Filestash` ist fuer diesen Ausbau ein guter Referenzdienst, weil:

- der Dienst stark storage-zentriert ist
- kein Spezialfall fuer GPU/Xorg/Steam/Sunshine noetig ist
- ein funktionierender Dateimanager direkt sichtbar macht, ob Mounts wirklich benutzbar sind
- der Dienst den `gaming-station`-Container nicht destabilisiert

Kurz:

- `gaming-station` bleibt unangetastet
- `Filestash` wird der saubere Referenzpfad fuer generische Storage-Volumes

---

## Zielbild

Ein neuer Datentraeger oder Mount soll kuenftig so durchlaufen:

1. Der User richtet ihn im `storage-broker` ein
2. Der Pfad wird hostseitig gemountet
3. Daraus wird ein publizierter Commander-Asset
4. `runtime-hardware` zeigt ihn als `mount_ref`
5. Simple Blueprint kann ihn grafisch auswaehlen
6. Der Commander-Deploy materialisiert daraus direkt einen Docker-Bind-Mount
7. Der Container kann sofort lesen und schreiben

Wichtig:

- kein App-spezifischer Sonderresolver
- kein Asset-ID-Hardcoding fuer einen einzelnen Dienst
- kein "nur fuer gaming" geschnittener Flow

---

## Belegter Ist-Zustand

Bereits vorhanden:

- `storage-broker` kann:
  - Datentraeger formatieren
  - mounten
  - Service-Storage provisionieren
  - Assets publizieren
- `runtime-hardware` kennt bereits:
  - `block_device_ref`
  - `mount_ref`
- der Commander-Deploypfad kann `mount_ref` bis in echte Container-Mounts materialisieren
- der Simple-Blueprint-Wizard zeigt bereits:
  - `block_device_ref`
  - `mount_ref`
- der Wizard speichert diese Auswahl als strukturierte `hardware_intents`

Bereits bekannte Luecken:

- `gaming-station` nutzt fuer `games` weiterhin zusaetzliche Sonderlogik statt ausschliesslich des generischen Blueprint-/`mount_ref`-Pfads
- Ownership-/Permissions muessen fuer weitere App-Typen weiter beobachtet werden
- die vorhandenen `gaming-station`-Postchecks haengen noch am alten Persistenz-Sollbild

---

## Architekturentscheidung

`Filestash` soll **nicht** mit App-spezifischer Storage-Sonderlogik gebaut werden.

Das bedeutet:

- keine festen Asset-IDs wie `filestash-data`
- kein Resolver, der gezielt einen Pfad erraten muss
- keine Sonderbehandlung im Commander fuer genau diese App

Stattdessen:

- `Filestash` wird als normaler Blueprint gebaut
- Storage kommt ausschliesslich ueber `hardware_intents`
- der eigentliche Bind-Mount entsteht ausschliesslich ueber `runtime-hardware` + `mount_ref`

Wenn das funktioniert, ist der Produktpfad fuer spaetere Dienste belastbar.

---

## Scope dieses Ausbaus

### In Scope

- neues Referenzpaket `filestash`
- neuer einfacher Blueprint fuer einen storage-zentrierten Dienst
- grafische Auswahl von publizierten `mount_ref`-Assets im Simple Blueprint
- Deploy in direkt funktionierende Docker-Mounts
- konsistente Schreibrechte fuer den Container-User

### Nicht in Scope

- Umbau von `gaming-station`
- Host-Sunshine-/Gaming-Themen
- Block-Device-Direktzugriff als Produktpfad
- komplexe Multi-Volume-Policy fuer alle denkbaren Apps

---

## Technisches Zielbild fuer Filestash

Der Filestash-Dienst soll spaeter mindestens folgendes koennen:

- als normales Marketplace-/Blueprint-Paket installierbar sein
- ohne Gaming-Komponenten funktionieren
- mindestens einen publizierten `mount_ref` als Nutzdatenpfad bekommen
- diesen Pfad sofort im Container sehen und benutzen koennen
- mit einem Standard-Deploy direkt startbar sein

Containerseitig angestrebtes Minimalbild:

- App-Konfig getrennt von Nutzdaten
- ein klarer Container-Zielpfad fuer den freigegebenen Storage
- keine versteckte Sonderauflosung im Deploy

### Bereits umgesetzt am 2026-03-28

- offizielles Marketplace-Paket `filestash` angelegt
- eigener Startup-Seeder fuer den Commander-Blueprint angelegt
- Admin-API seedet den Blueprint beim Start automatisch
- erster Referenz-Blueprint verwendet:
  - Image: `machines/filestash:latest`
  - Port: `8334/tcp`
  - persistenter Zustand ueber Docker-Volume `filestash_state -> /app/data/state`
- `Filestash` mountet publizierte Broker-Assets jetzt zur Laufzeit automatisch unter:
  - `/srv/storage-broker/<asset-id>`
- `Filestash` schreibt daraus automatisch lokale Verbindungen in seine laufende `config.json`
- die Live-Ansicht zeigt damit **nur** Storage, der ueber den Broker/Commander publiziert wurde
- `runtime-hardware` liefert fuer `mount_ref` jetzt zusaetzlich:
  - `default_container_path`
  - `broker_managed`
- der Simple-Wizard speichert fuer `mount_ref` jetzt automatisch:
  - `policy.mode`
  - `policy.container_path`
- Standard-Zielpfad fuer generische `mount_ref`-Deploys:
  - `/storage/<asset-id-slug>`
- der Commander materialisiert diesen Pfad beim Deploy direkt als Docker-Bind-Mount

Live belegt:

- laufender Filestash-Container:
  - `trion_filestash_1774737807646_b83468`
- automatische Broker-Mounts im Container:
  - `/srv/storage-broker/sb-managed-services-containers`
  - `/srv/storage-broker/gaming-station-games`
- `TRION / ...`-Verbindungen stehen real in:
  - `/app/data/state/config/config.json`
- `runtime-hardware`-Live-API zeigt `mount_ref` jetzt mit:
  - `default_container_path=/storage/<asset>`
- generischer Smoke-Test-Blueprint `simple-storage-smoke` wurde live deployed und hat den Games-Asset direkt als:
  - `/mnt/games/services/gaming-station-games/data -> /storage/gaming-station-games`
  - materialisiert
- Schreibtest im laufenden Smoke-Container auf `/storage/gaming-station-games`:
  - erfolgreich
- der Wegwerf-Blueprint und der Testcontainer wurden danach wieder entfernt

Wichtige bewusste Entscheidung:

- Der erste Seed nutzt **kein Host-Bind fuer App-State**, sondern ein Docker-Volume.
- Grund:
  - so startet der Referenzdienst robuster
  - die generische Storage-Integration soll ueber zusaetzliche publizierte Mounts getestet werden, nicht ueber app-spezifische Host-Bind-Sonderfaelle

---

## Offene Produktfragen

Diese Punkte muessen fuer den generischen Pfad entschieden oder gehaertet werden:

### 1. Wann ist ein Storage-Asset deploy-ready?

Ein `mount_ref` sollte nur dann im Produktpfad auftauchen, wenn mindestens gilt:

- Host-Pfad existiert
- `published_to_commander=true`
- `default_mode` ist gueltig
- Policy erlaubt den Zugriff
- Ownership/Permissions sind fuer den Ziel-User geklaert

### 2. Wie wird der Zielpfad im Container bestimmt?

Es braucht einen sauberen Produktvertrag:

- App gibt gewuenschten Container-Zielpfad vor
- oder der Wizard fragt ihn explizit ab
- aber nicht implizit ueber app-spezifische Sonderlogik

### 3. Wie werden Permissions gesetzt?

Der Standardpfad muss konsistent regeln:

- Owner
- Group
- Modus
- Schreibrechte fuer den Container-User

ohne manuelles Nachziehen pro App.

### 4. Wie wird der grafische Flow abgeschlossen?

Der User soll spaeter durchgaengig koennen:

- Datentraeger im Storage-Broker vorbereiten
- Pfad publizieren
- im Simple Blueprint waehlen
- deployen

ohne weiteren manuellen Commander-Sonderpfad.

---

## Implementationsphasen

## Phase 0: Referenzdienst festziehen

Ziel:

- `Filestash` als neuer, bewusst einfacher Referenzdienst wird eingefuehrt

Arbeitspunkte:

- Paket-/Blueprint-Schnitt festlegen
- klaeren, welcher Container-Zielpfad fuer Daten genutzt wird
- Minimalanforderungen an Konfig + Datenmount festlegen

Abnahmekriterium:

- klarer Paketvertrag fuer `filestash`
- kein Spezialwissen aus `gaming-station` noetig

Status:

- weitgehend umgesetzt
- offen ist nur noch, den generischen Datenpfad fuer zusaetzliche publizierte Storage-Mounts produktiv anzuschliessen

## Phase 1: Generischen Storage-Vertrag schaerfen

Ziel:

- publizierte Storage-Assets sind klar als deploybar oder nicht deploybar klassifiziert

Arbeitspunkte:

- Definition fuer "deploy-ready mount_ref"
- Ownership-/Permission-Felder im Standardpfad klaeren
- `allowed_for`-/Usage-Modell fuer generische Container sauber festziehen

Abnahmekriterium:

- ein publizierter Pfad hat genug Metadaten fuer einen direkten Deploy

Status:

- umgesetzt fuer den generischen `mount_ref`-Produktpfad
- aktueller Standardvertrag:
  - publiziertes Asset
  - gueltiger `default_mode`
  - `default_container_path`
  - direkte Materialisierung als Docker-Bind-Mount

## Phase 2: Simple-Blueprint-Flow schliessen

Ziel:

- der grafische Blueprint-Flow kann publizierte `mount_ref`-Assets sinnvoll waehlen

Arbeitspunkte:

- Simple Blueprint soll `mount_ref` nicht nur anzeigen, sondern als echten Produktpfad fuehren
- Zielpfad, Zugriffsmodus und Mount-Vertrag muessen sauber aus dem Wizard in `hardware_intents`
- keine app-spezifische Resolver-Magie

Abnahmekriterium:

- ein im Wizard gewaehlter `mount_ref` fuehrt spaeter deterministisch zu einem Deploy-Mount

Status:

- live belegt
- der Wizard speichert jetzt fuer `mount_ref` automatisch einen sicheren Standard-Zielpfad
- der generische Smoke-Test hat den Docker-Bind-Mount direkt materialisiert

## Phase 3: Filestash als erster echter Testdienst

Ziel:

- `Filestash` laeuft ueber genau diesen generischen Storage-Pfad

Arbeitspunkte:

- Paket und Blueprint anlegen
- Standard-Deploy ueber Commander testen
- Datenpfad im Container pruefen
- Schreib-/Lesetest ueber die App oder direkt im Container

Abnahmekriterium:

- `Filestash` startet
- sieht den publizierten Mount
- kann darauf schreiben

## Phase 4: Generalisierung absichern

Ziel:

- der Flow ist nicht nur fuer `Filestash`, sondern generisch wiederverwendbar

Arbeitspunkte:

- keine Filestash-spezifische Sonderlogik im Resolver belassen
- UI-/Deploy-Verhalten fuer weitere Dienste uebertragbar halten
- `gaming-station` spaeter auf denselben Pfad migrierbar machen

Abnahmekriterium:

- die Filestash-Integration beweist den generischen Produktpfad

---

## Konkrete TODOs

- neues Marketplace-Paket `filestash` vorbereiten
- einfachen Filestash-Blueprint definieren
- Ziel-Datenpfad fuer Container festlegen
- Standard-Asset-/Mount-Vertrag fuer `mount_ref` schaerfen
- Simple-Blueprint-UX fuer `mount_ref` bis zum fertigen Docker-Mount absichern
- Permissions-/Ownership-Pfad fuer Container-User standardisieren
- Referenztest mit einem publizierten Storage-Asset gegen echten Deploy fahren

---

## Akzeptanzkriterien

Der Ausbau ist fachlich erfolgreich, wenn:

- ein User einen Datentraeger ueber `storage-broker` vorbereiten kann
- daraus ein publizierter Commander-Asset entsteht
- dieser Asset im Simple Blueprint als `mount_ref` waehlbar ist
- der Deploy daraus direkt einen funktionierenden Docker-Bind-Mount erzeugt
- `Filestash` diesen Pfad sofort benutzen kann
- dafuer keine dienstspezifische Mount-Sonderlogik noetig ist

---

## Wichtig fuer den weiteren Verlauf

`Filestash` ist hier der Referenzdienst.

Erst wenn dieser generische Pfad sauber funktioniert, sollte `gaming-station` von seiner heutigen Sonderlogik auf denselben Produktpfad umgezogen werden.
