# Gaming-Station Games-Storage-Integration — Implementationsplan

Stand: 2026-03-28
Status: Gestoppt und archiviert am 2026-04-01. Historischer Integrationsstand.

Hinweis: Diese Notiz bleibt als Referenz fuer den frueheren `gaming-station`-Games-Storage-Pfad erhalten, der operative Zweig ist archiviert.

## Update 2026-03-28

Der erste nicht-destruktive Integrationsschritt ist umgesetzt:

- der Commander-Asset-Store akzeptiert jetzt zusaetzlich `allowed_for=["games"]`
- die Storage-Broker-UI bietet dafuer jetzt den Verwendungszweck `Spielebibliothek`
- `gaming-station` kann einen publizierten Games-Asset jetzt automatisch als `/games` mounten
- Prioritaet fuer die automatische Auswahl:
  - explizite Asset-IDs `gaming-station-games`, `games`, `sb-games`
  - danach publizierte Assets mit `allowed_for=["games"]`
- der Storage-Broker kann Service-Storage jetzt zusaetzlich unter einem **explizit gewaehlten managed base** provisionieren statt immer nur unter dem ersten Basispfad
- der Setup-Wizard gibt den gewaehlten Mountpoint jetzt als `base_path` weiter
- der Host-Helper-/Broker-Mountpfad kann Mountpoints jetzt vorab erzeugen und optional einen persistierenden `/etc/fstab`-Eintrag schreiben
- fuer `allowed_for="games"` zeigt die Asset-Aufloesung jetzt auf den nutzbaren `data`-Pfad statt auf den gesamten Service-Root

Seit dem spaeteren Live-Apply am selben Tag ist der Host-/Container-Pfad jetzt zusaetzlich belegt:

- `/dev/sdd1` wurde mit `ext4` formatiert
- Label: `games`
- Host-Mount:
  - `/mnt/games`
- Persistenz:
  - `/etc/fstab` enthaelt einen UUID-basierten Eintrag fuer `/mnt/games`
- provisionierter Service-Storage:
  - `/mnt/games/services/gaming-station-games/config`
  - `/mnt/games/services/gaming-station-games/data`
  - `/mnt/games/services/gaming-station-games/logs`
- publizierter Commander-Asset:
  - `gaming-station-games -> /mnt/games/services/gaming-station-games/data`
  - `allowed_for=["games"]`
- `gaming-station` bindet diesen Asset jetzt als:
  - `/games`

Zusaetzlicher Architektur-Fix im Commander:

- `ensure_package_storage_scope()` merged jetzt deklarierte Package-Roots mit zusaetzlichen Blueprint-Bind-Mounts
- dadurch blockiert `storage_scope` neue dynamische Storage-Assets wie `/games` nicht mehr
- der vorherige Fehler
  - `storage_scope_violation: mount '/mnt/games/services/gaming-station-games/data' is outside scope 'gaming-station-host-bridge'`
  - ist damit fuer diesen Pfad behoben

Live-Verifikation:

- laufender Verifikationscontainer:
  - `trion_gaming-station_1774733745385_d67321`
- Docker-Mount:
  - `/mnt/games/services/gaming-station-games/data -> /games`
- im Container:
  - `/dev/sdd1 on /games type ext4 (rw,noatime)`
- Schreibtest als Container-User `default`:
  - erfolgreich

Weiterer Stand am selben Tag:

- `gaming-station` materialisiert jetzt im Fallback ohne Host-Assets zusaetzlich explizite Docker-Volumes fuer
  - `/home/default/.steam`
  - `/home/default/.local/share`
- die Package-Postchecks akzeptieren jetzt explizite persistente Mounts fuer diese Ziele, statt nur das alte Host-Bind-Sollbild
- ein frischer Produktdeploy lief danach erfolgreich als
  - `trion_gaming-station_1774739490165_6b6567`
- Live-Mounts im neuen Container:
  - `gaming_steam_home -> /home/default/.steam`
  - `gaming_user_data -> /home/default/.local/share`
  - `/mnt/games/services/gaming-station-games/data -> /games`

Praezise Bedeutung dieser beiden Checks:

- `steam_home_persistent`
  - erwartet exakt den Mount:
  - `/home/default/.steam -> /data/services/gaming-station/data/steam-home`
- `user_data_persistent`
  - erwartet exakt den Mount:
  - `/home/default/.local/share -> /data/services/gaming-station/data/userdata`

Wichtige Einordnung:

- historisch prueften diese Checks nur dieses hart codierte Hostpfad-Sollbild
- der Produktpfad ist jetzt breiter:
  - alte Host-Binds bleiben gueltig
  - explizite Docker-Volumes fuer diese Ziele gelten ebenfalls als persistenter Mount

## Zielbild

`gaming-station` soll zusaetzlich zu seinem App-/Config-State einen stabilen Games-Pfad aus dem Storage-Broker erhalten.

Gewuenschtes Produktbild:

- der Datentraeger `games` wird hostseitig sauber materialisiert
- der Commander sieht ihn als publizierten `mount_ref`
- `gaming-station` bindet diesen Pfad als benutzbaren Mount ein
- Steam nutzt diesen Pfad als Library-Ziel
- der Container bekommt **keine** rohe Partition als Standardpfad durchgereicht

Kurz:

- **nicht** `/dev/sdd1` direkt im Container benutzen
- **sondern** Host-Mount -> Commander-Asset -> `mount_ref` -> Containerpfad

---

## Belegter Ist-Zustand

Die folgenden Punkte sind fuer den aktuellen Host und den aktuellen Commander-Stand direkt belegt:

- `/dev/sdd1` existiert als Partition mit `PARTLABEL=games`
- Groesse: `500 GiB`
- `lsblk` zeigt fuer `/dev/sdd1` aktuell:
  - `FSTYPE=ext4`
  - `LABEL=games`
  - `MOUNTPOINTS=/mnt/games`
- der Storage-Broker fuehrt `/dev/sdd1` als:
  - `policy_state=managed_rw`
  - `zone=managed_services`
  - `allowed_operations=["create_directory","set_permissions","assign_to_container","create_service_storage"]`
- Runtime-Hardware sieht `/dev/sdd1` weiterhin auch als:
  - `container::block_device_ref::/dev/sdd1`
- zusaetzlich existiert jetzt ein publizierter Games-Asset:
  - `gaming-station-games -> /mnt/games/services/gaming-station-games/data`
- der gespeicherte `gaming-station`-Blueprint hat aktuell:
  - `hardware_intents=[]`
- `managed_bases=["/data", "/mnt/games"]`
- `/data` liegt aktuell auf dem Root-Filesystem, **nicht** auf `sdd1`

Damit ist der aktuelle Zustand klar:

- Storage-Broker und Commander sind verdrahtet
- fuer `games` existieren jetzt sowohl Rohgeraete- als auch benutzbarer Mount-/Asset-Pfad
- der verbleibende Rest sitzt nicht mehr im Storage-Broker-Materialisierungspfad, sondern im normalen `gaming-station`-Postcheck-Deploypfad

## TODO aus aktuellem Ist-Stand

Die Basisintegration funktioniert, aber der Produktpfad ist noch nicht generisch genug.

### Bereits faktisch erreicht

- Storage-Broker kann Datentraeger formatieren, mounten, Service-Storage provisionieren und Assets publizieren
- `runtime-hardware` kennt bereits:
  - `block_device_ref`
  - `mount_ref`
- der Engine-Deploypfad kann publizierte `mount_ref`-Assets bis in echte Container-Mounts materialisieren
- der grafische Simple-Blueprint-Flow ist fuer `block_device_ref` und `mount_ref` bereits sichtbar vorbereitet

### Noch offen

- `gaming-station` nutzt fuer die Asset-Auswahl fuer `games` aktuell noch eine gaming-spezifische Priorisierung in `mcp_tools_gaming.py`
  - Asset-IDs wie `gaming-station-games`, `games`, `sb-games`
- der eigentliche Deploypfad ist aber jetzt auf den generischen Blueprint-/`hardware_intents`-/`mount_ref`-Mechanismus umgestellt
  - Zielpfad bleibt bewusst `/games`
  - der statische `/games`-Bind-Mount ist aus dem Blueprint entfernt
- der grafische Flow "Datentraeger im Storage-Broker anlegen -> als Asset publizieren -> im Simple Blueprint auswaehlen -> als Volume deployen" ist jetzt fuer den generischen Referenzpfad live belegt
- offener Rest ist hier nur noch, `gaming-station` selbst von der Sonderlogik auf denselben generischen Pfad umzuziehen
- Ownership-/Permissions fuer neu provisionierte Games-Pfade muessen im Standardflow konsistent fuer den Container-User gesetzt werden
- die alten `gaming-station`-Postchecks blockieren den normalen Deploypfad noch am historischen Persistenz-Sollbild und muessen an den heutigen Produktpfad angepasst werden

## Update 2026-03-28 — sicherer Zwischenschritt umgesetzt

Der risikoarme Zwischenschritt ist jetzt umgesetzt:

- `gaming-station` behaelt den Container-Zielpfad:
  - `/games`
- der gespeicherte Blueprint nutzt dafuer aber jetzt einen generischen `hardware_intent`:
  - `container::mount_ref::gaming-station-games`
  - `policy.container_path=/games`
- der statische Blueprint-Mount
  - `/mnt/games/services/gaming-station-games/data -> /games`
  - wurde entfernt

Wichtige Einordnung:

- damit aendert sich fuer Steam/den Containerpfad bewusst nichts
- geaendert wurde nur die Quelle des Mounts:
  - nicht mehr statisch im Blueprint
  - sondern ueber den generischen `runtime-hardware`-/`mount_ref`-Deploypfad
- der laufende `gaming-station`-Container wurde dabei **nicht** neu deployed oder ersetzt

---

## Architekturentscheidung

Fuer `gaming-station` wird `games` als **Storage-Pfad** behandelt, nicht als Blockdevice.

Das bedeutet:

- `block_device_ref` bleibt ein Diagnose-/Sonderfall fuer explizite Rohgeraete-Nutzung
- der Produktpfad fuer Spielebibliotheken ist `mount_ref`
- die Storage-Broker-Einrichtung soll aus verwaltetem Storage moeglichst direkt einen Commander-tauglichen Asset machen

---

## Zielintegration

### Host-Seite

Hostseitig muss `games` in einen stabilen Pfad ueberfuehrt werden, z. B.:

- `/srv/trion/games`
- oder `/mnt/games`
- oder ein anderer klarer, persistenter Host-Mountpunkt

Dieser Pfad muss:

- ein reales Dateisystem enthalten
- sauber gemountet sein
- vom Storage-Broker als verwalteter Pfad validierbar sein

### Commander-Seite

Der Pfad soll danach als publiziertes Storage-Asset sichtbar werden, z. B.:

- Asset-ID: `sb-games`
- Pfad: `/mnt/games`
- `published_to_commander=true`
- `default_mode=rw`
- `allowed_for=["workspace"]` oder neuer passender Usage-Typ fuer Games

### Blueprint-Seite

`gaming-station` soll diesen Asset dann als `mount_ref` konsumieren, z. B.:

- Host-Pfad: `asset:sb-games`
- Container-Pfad: `/games`

Danach kann Steam im Container dort eine Library anlegen.

---

## Was heute noch fehlt

### 1. Storage-Broker-Ende-zu-Ende-Pfad fuer Games-Volumes

Heute gibt es zwar:

- Formatieren
- Mounten
- Service-Dir-Provisioning
- Asset-Publikation

aber noch keinen klaren, dokumentierten Produktpfad fuer:

- verwaltete Partition `games`
- als eigenstaendiger Mount
- als direkt nutzbares Commander-Asset
- fuer einen Container wie `gaming-station`

### 2. Passender Asset-Typ / Usage fuer Games

Aktuell kennt der Asset-Store:

- `appdata`
- `media`
- `backup`
- `workspace`

Fuer eine Steam-Library ist `workspace` am ehesten nutzbar, fachlich aber nicht ideal.

Es fehlt eine klare Entscheidung:

- `workspace` wiederverwenden
- oder einen dedizierten Usage-Typ wie `games` einfuehren

### 3. Blueprint-Anbindung

`gaming-station` fordert den Storage heute noch nicht an.

Es fehlt:

- publizierter Asset
- `hardware_intent` oder direkter Mount-Asset-Eintrag
- definierter Container-Zielpfad

---

## Empfohlene Implementationsreihenfolge

### Phase 1: Datentraeger sauber materialisieren

Ziel:

- `/dev/sdd1` bekommt einen verifizierten, nutzbaren Host-Mountpunkt

Arbeitspunkte:

- Dateisystemstatus final pruefen
- falls leer: bewusst formatieren
- stabilen Mountpoint festlegen
- Mount ueber Storage-Broker ausfuehrbar und reproduzierbar machen

Abnahmekriterium:

- `/dev/sdd1` ist mit Dateisystem versehen
- Host sieht einen stabilen Mountpoint
- Storage-Broker erkennt den Pfad sauber

### Phase 2: Commander-Asset fuer Games publizieren

Ziel:

- der Host-Mount erscheint als publizierter `mount_ref`

Arbeitspunkte:

- Asset-ID und Label festlegen
- `published_to_commander=true`
- passenden Usage-Typ festlegen
- pruefen, dass Runtime-Hardware den `mount_ref` sichtbar macht

Abnahmekriterium:

- `container::mount_ref::<asset>` erscheint in Runtime-Hardware
- der Asset ist im Commander registriert

### Phase 3: `gaming-station` anbinden

Ziel:

- `gaming-station` kann den Games-Pfad als Container-Mount erhalten

Arbeitspunkte:

- Blueprint um Games-Asset erweitern
- Zielpfad im Container definieren, bevorzugt `/games`
- Storage-Scope fuer diesen Asset validieren

Abnahmekriterium:

- frischer Deploy mountet den Games-Pfad in den Container
- der Container sieht dort schreibbaren Storage

### Phase 4: Steam-Library sauber darauf ausrichten

Ziel:

- Steam nutzt den neuen Mount praktisch

Arbeitspunkte:

- Steam-Library-Ziel definieren
- ggf. First-Run-/Library-Erstellung dokumentieren
- Verhalten bei leerem oder fehlendem Games-Mount definieren

Abnahmekriterium:

- Steam kann auf dem neuen Pfad eine Library anlegen und Spiele installieren

---

## Nicht-Ziele

Diese Integration soll **nicht** bedeuten:

- rohe Partition standardmaessig in den Container geben
- Container selbst formatieren oder mounten lassen
- `gaming-station` vom Container aus Host-Storage manipulieren lassen

Der Mount-/Format-/Asset-Pfad bleibt Host-/Broker-gesteuert.

---

## Offene Entscheidungen

Vor Umsetzung muessen diese Punkte klar entschieden werden:

- finaler Host-Mountpunkt fuer `games`
- Dateisystem fuer `sdd1`
- Asset-Usage:
  - `workspace`
  - oder neuer Typ `games`
- Container-Zielpfad:
  - `/games`
  - oder direkter Steam-Library-Pfad

---

## Erwartetes Endergebnis

Wenn dieser Plan umgesetzt ist, gilt fuer `gaming-station`:

- Sunshine bleibt auf dem Host
- Steam bleibt im Container
- grosse Spieledaten liegen auf dem separaten `games`-Datentraeger
- der Datentraeger wird reproduzierbar ueber Storage-Broker + Commander eingebunden
- ein Wiederaufbau ist ohne improvisierte Host-Mounts nachvollziehbar
