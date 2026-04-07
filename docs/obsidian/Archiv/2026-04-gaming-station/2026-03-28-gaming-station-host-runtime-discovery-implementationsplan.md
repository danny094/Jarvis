# Gaming-Station Host-Runtime-Discovery — Implementationsplan

Stand: 2026-03-28
Status: Gestoppt und archiviert am 2026-04-01. Historischer Implementationsstand.

Hinweis: Dieser Plan bleibt als Architekturhistorie erhalten, der zugehoerige `gaming-station`-Arbeitszweig ist aber nicht mehr aktiv.

## Zielbild

`gaming-station` bleibt ein Host-Bridge-/`MODE=secondary`-Blueprint.

Der Container soll:

- Steam, Spiele und App-State tragen
- den Host-Display-/Pulse-Pfad nutzen
- **keine** Sunshine-Installation auf dem Host ausloesen
- **keine** Host-Dateien fuer Sunshine schreiben
- **keinen** Host-Service `enable`n oder `start`en

Der Deploy soll nur noch den Host-Befund melden:

- `Sunshine auf dem Host gefunden`
- oder `Sunshine auf dem Host nicht gefunden`

---

## Warum der Scope geaendert wurde

- Der experimentelle `primary`-Pfad mit Sunshine im selben Container war diagnostisch nuetzlich, aber nicht robust genug fuer das Produktziel.
- Der stabile Architekturpfad bleibt deshalb:
  - Sunshine auf dem Host
  - Steam im Container
- Der bisherige `host_companion`-Pfad war fuer lokale Materialisierung hilfreich, ist aber fuer den gewuenschten Produktpfad zu mutierend.

Kurz:

- **weg von** Host-Mutation
- **hin zu** Host-Runtime-Discovery

---

## Neuer Scope

### Was `gaming-station` weiterhin machen darf

- Container deployen
- Host-X11/Pulse-Pfade nutzen
- Host-Zustand pruefen
- Warnungen/Status an den Deploy haengen

### Was `gaming-station` nicht mehr machen soll

- `sunshine-host.service` auf den Host schreiben
- Sunshine-Binaries auf den Host installieren
- `apt install` auf dem Host anstossen
- `systemctl --user daemon-reload`
- `systemctl --user enable`
- `systemctl --user start`

---

## Architektur-Schnitt

### 1. `engine_start_support.py` bleibt Orchestrierung

`container_commander/engine_start_support.py` soll nicht weiter mit Host-spezifischer Sonderlogik aufgeladen werden.

Es soll nur:

- den Package-/Runtime-Typ erkennen
- eine generische Host-Runtime-Pruefung aufrufen
- das Ergebnis als `ok`, `warning` oder `block` behandeln

### 2. Neues Modul fuer read-only Host-Runtime-Checks

Neues Modul:

- `container_commander/host_runtime_discovery.py`

Verantwortung:

- Host-Runtimes erkennen
- nur lesen, nie schreiben
- keine Installation
- keine Materialisierung
- keine Reparatur

### 3. `host_companions.py` bleibt mutierender Pfad

`container_commander/host_companions.py` bleibt fuer echte Host-Companions erhalten.

Aber:

- `gaming-station` soll diesen Pfad im neuen Produkt-Scope nicht mehr benutzen

---

## Erwartete Manifest-Erweiterung

Statt mutierendem `host_companion` braucht `gaming-station` kuenftig eine read-only Deklaration, z. B.:

```json
"host_runtime_requirements": {
  "sunshine": {
    "required": false,
    "discovery": {
      "systemd_user_units": ["sunshine-host.service", "sunshine.service"],
      "binary_candidates": [
        "$HOME/.local/opt/sunshine/sunshine.AppImage",
        "/usr/bin/sunshine"
      ],
      "port_candidates": [47990]
    }
  }
}
```

Wichtig:

- Das ist eine **Deklaration**
- kein Install- oder Startauftrag

---

## Discovery-Regeln

Die Sunshine-Erkennung soll deterministisch und read-only sein.

### Reihenfolge

1. Bekannte `systemd --user`-Units pruefen
2. Valide Sunshine-Binaries pruefen
3. Optional bekannte Host-Ports pruefen

### Erfolgskriterien

`Sunshine auf dem Host gefunden`, wenn mindestens ein belastbarer Befund vorliegt:

- User-Service vorhanden und `active`
- oder valides Sunshine-Binary vorhanden und durch konfigurierten Service referenziert
- optional zusaetzlich Host-Port/WebUI erreichbar

### Misserfolg

`Sunshine auf dem Host nicht gefunden`, wenn:

- kein valider User-Service gefunden wird
- und kein valides Sunshine-Binary an den bekannten Kandidaten liegt

---

## API-/Engine-Verhalten

### Deploy

Beim Deploy von `gaming-station`:

- Container normal starten
- read-only Host-Runtime-Discovery ausfuehren
- Befund als Deploy-Status/Warnung anhaengen

### Gewuenschte Ergebnisformen

- `ok`
  - Sunshine erkannt
  - Verbindungshinweis anzeigen
- `warning`
  - Sunshine nicht erkannt
  - Container darf trotzdem laufen
- kein automatischer Repair

### Kein Blocker im Standardfall

Empfehlung fuer `gaming-station`:

- kein harter Deploy-Abbruch nur wegen fehlendem Host-Sunshine
- stattdessen klare Warning

---

## Umsetzungsstand

Bereits umgesetzt:

- `container_commander/host_runtime_discovery.py` existiert
- `gaming-station` nutzt read-only Host-Runtime-Checks statt Host-Mutation
- `engine_start_support.py` behandelt diesen Pfad als Discovery-/Statuspfad
- `gaming-station/package.json` ist auf `host_runtime_requirements` umgestellt
- der Deploy erkennt Host-Sunshine wieder und meldet den Befund
- `gaming-station` installiert oder startet Sunshine auf dem Host nicht mehr

Offen in diesem Scope:

- nur noch Feinschliff fuer Status-/UI-Darstellung
- keine grundlegende Architekturarbeit mehr

## TODO aus aktuellem Ist-Stand

Die Architektur ist im Kern vorhanden, aber noch nicht voll produktisiert.

### Bereits faktisch erreicht

- `gaming-station` ist als optionales Marketplace-Paket getrennt vom Rest des Stacks nutzbar
- der Produktpfad fuer Host-Sunshine ist read-only Discovery statt Host-Mutation
- der User muss hostseitig nur Sunshine selbst bereitstellen; `gaming-station` installiert oder startet es nicht mehr

### Noch offen

- die Host-Discovery ist noch zu hostnah hardcoded
  - User `danny`
  - UID/GID `1000`
  - Host-Pfade unter `$HOME/...`
  - feste Service-Namen wie `sunshine-host.service`
- diese Werte muessen kuenftig aus Host-Kontext, Settings oder Runtime-Erkennung kommen statt aus fest verdrahteten Defaults
- historischer Host-Companion-Altbestand fuer `gaming-station` ist noch im Repo vorhanden und verwischt den Zielzustand
- UI-/Deploy-Status fuer "Sunshine gefunden / nicht gefunden" sollte noch klarer vom Alt-Host-Companion-Modell getrennt werden

## Konkrete Implementationsschritte

### Phase 1: Discovery-Modul einfuehren

- [x] `container_commander/host_runtime_discovery.py` angelegt
- [x] read-only Helper fuer:
  - `systemctl --user is-active`
  - `systemctl --user list-units`
  - Host-Pfadpruefung
  - optionale Port-Pruefung
- [x] strukturierte Rueckgabe definiert:
  - `found`
  - `status`
  - `service_name`
  - `binary_path`
  - `port_reachable`
  - `details`

### Phase 2: Manifest-Scope einfuehren

- [x] neues Manifest-Feld fuer read-only Host-Runtime-Anforderungen definiert
- [x] `gaming-station/package.json` darauf umgestellt
- [x] `host_companion` fuer `gaming-station` im Produktpfad auf Discovery-Only reduziert; Altbestand bleibt nur dokumentarisch relevant

### Phase 3: Engine anbinden

- [x] `engine_start_support.py` ruft generisch den Host-Runtime-Check auf
- [x] Ergebnis wird als Warning/Status in den Deploy uebernommen
- [x] keine Host-Mutation mehr fuer `gaming-station`

### Phase 4: UI-/Status-Nachricht

- [x] User-facing Meldung vereinheitlicht:
  - `Sunshine auf dem Host gefunden`
  - `Sunshine auf dem Host nicht gefunden`
- [ ] optional Details anhaengen:
  - gefundener Service
  - gefundener Binary-Pfad
  - erkannter WebUI-Port

### Phase 5: Altpfad entschaerfen

- [x] `ensure_host_companion(...)` nicht mehr im alten Mutationssinn fuer `gaming-station` verwenden
- [x] vorhandene mutierende Sunshine-/Host-Datei-Logik fuer `gaming-station` aus dem Produkt-Startpfad abgekoppelt
- [x] bestehende Historie nur noch dokumentarisch erhalten

---

## Tests

### Positiv

- [x] Host hat aktiven `sunshine-host.service`
- [x] Deploy meldet `Sunshine auf dem Host gefunden`
- [x] Container startet ohne Host-Mutation

### Negativ

- [ ] Host hat keinen Sunshine-Service und kein Binary
- [ ] Deploy meldet `Sunshine auf dem Host nicht gefunden`
- [ ] Container startet trotzdem

### Regression

- [x] `gaming-station` schreibt keine Host-Dateien mehr
- [x] `gaming-station` fuehrt kein Host-`apt install` mehr aus
- [x] `gaming-station` fuehrt kein Host-`systemctl --user start/enable` mehr aus

---

## Abgrenzung

Dieser Plan aendert **nicht**:

- den `gaming-test`-Diagnosepfad
- die generische Runtime-Hardware-Logik
- die Storage-Scope-Haertung fuer Runtime-Binds

Dieser Plan aendert **nur**:

- wie `gaming-station` Host-Sunshine behandelt
- weg von Materialisierung
- hin zu Discovery und Statusmeldung

---

## Erfolgskriterium

Der Scope ist erreicht, wenn ein frischer `gaming-station`-Deploy:

- Steam im Container startet
- keinerlei Sunshine-Dateien auf dem Host materialisiert
- keinerlei Host-Service fuer Sunshine schreibt oder startet
- und dem User nur noch klar meldet:
  - `Sunshine auf dem Host gefunden`
  - oder `Sunshine auf dem Host nicht gefunden`
