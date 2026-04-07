# Implementationsplan — 2026-03-24 (aktualisiert 2026-03-25, Quality-Session)

Für ADHD-Danny und ADHD-K-Claude.
Reihenfolge ist bewusst gewählt: erst Diagnose, dann Fixes, dann Tuning.
Jede Phase ist unabhängig abschließbar. Nie zwei Baustellen gleichzeitig.

> **Architektur-Update 2026-03-25:** Gaming Station läuft jetzt in MODE=primary.
> Sunshine ist im Container, kein Host-Dienst mehr. Phase 2 entfällt dadurch vollständig.
> Phasen 3–6 bleiben gültig.

---

## Warum diese Reihenfolge?

```
Pairing    →  Session-Stabilität  →  Controller  →  Container  →  Tuning  →  TRION
(blind)       (Restart-Loop-Risiko)  (neu testen)   (Lifecycle)   (nice2have)  (separat)
```

Moonlight geht nicht → kein Streaming-Test möglich → alles andere ist raten.
Deshalb zuerst Pairing, dann alles andere.

---

## Phase 1: Pairing sehen und reparieren ✅ ERLEDIGT (2026-03-24)

**Ziel:** Herausfinden warum Moonlight nicht sauber pairt und das einmalig sauber durchführen.

**Kontext:** Credentials wurden am 23.03. resettet. Moonlights altes Cert ist ungültig. `min_log_level=2` macht den Pairing-Flow unsichtbar.

### Schritte

- [x] **1.1** `min_log_level` auf `0` setzen
- [x] **1.2** Sunshine neu starten
- [x] **1.3** Moonlight Host-Eintrag auf dem Mac löschen (via PlistBuddy)
- [x] **1.4** Log beobachten
- [x] **1.5** Pairing durchführen → PIN eingeben
- [x] **1.6** Erfolg bestätigt: `named_devices` enthält `macbook`
- [x] **1.7** Sunshine auf v2025.924.154138 aktualisiert

### Was den Fix ausgemacht hat

**Eigentliche Ursache:** `cert` und `pkey` waren in `sunshine.conf` nicht explizit gesetzt. Sunshine generiert seit neueren Versionen kein `cert.pem`/`key.pem` mehr automatisch — es erwartet, dass `cacert.pem`/`cakey.pem` als Pairing-Zertifikat verwendet werden. Ohne explizite Config war der `getservercert`-Handler defekt (hing nach PIN-Eingabe).

**Fix in `~/.config/sunshine/host-test/sunshine.conf`:**
```
cert = $HOME/.config/sunshine/credentials/cacert.pem
pkey = $HOME/.config/sunshine/credentials/cakey.pem
```

**Warum so lange:** Moonlight speichert sein Client-Cert in `~/Library/Preferences/com.moonlight-stream.Moonlight.plist` (nicht im macOS Keychain). Das Pairing scheiterte still nach `getservercert` weil Sunshine zwar "Erfolg" meldete, aber die Antwort kryptografisch nicht zum Signatur-Key passte. `clientchallenge` wurde von Moonlight nie gesendet. `named_devices` blieb leer.

**Geholfen hat:** ChatGPT + Claude Desktop Analyse des exakten GFE-Pairing-Flows.

**Aktueller Zustand:**
- Sunshine v2025.924.154138 läuft
- `named_devices` enthält `macbook` (UUID: 3F0AF166-922B-2826-619B-3600BC110F73)
- `min_log_level = 0` (noch aktiv — nach stabilem Betrieb auf `2` zurücksetzen)

---

## Phase 2: X-Socket Stop-Path absichern ✅ ENTFÄLLT (2026-03-25)

**Grund:** Host-Sunshine-Service (`sunshine-host.service`) wurde vollständig entfernt.
Sunshine läuft jetzt im Container (MODE=primary). Kein Host-Xorg, kein X-Socket-Problem mehr.

~~Ziel: Verhindern dass ein unsauberer Sunshine-Stop eine Restart-Schleife auslöst.~~

---

## Phase 3: Bluetooth Controller stabilisieren

**Ziel:** DS4 stabil verbinden. Steam-Input im Container testen.

**Kontext (aktualisiert 2026-03-25):** In MODE=primary erbt der Container `/dev/input/*` direkt via
Device-Passthrough (`ENABLE_EVDEV_INPUTS=true`). Kein Host-Sunshine-Input-Pfad mehr.
Controller muss auf dem Host gepairt sein — Container sieht ihn dann automatisch.

### Schritte

- [ ] **3.1** DS4 Controller einschalten (PS-Taste gedrückt halten)

- [ ] **3.2** Host-Verbindung prüfen:
  ```bash
  bluetoothctl info 58:10:31:39:50:06
  ```
  Erwartung: `Connected: yes`

- [ ] **3.3** Falls `Authentication Failed`:
  ```bash
  bluetoothctl remove 58:10:31:39:50:06
  bluetoothctl scan on  # dann: pair / trust / connect
  ```

- [ ] **3.4** Container-Sicht prüfen:
  ```bash
  CNAME=$(docker ps --filter 'name=trion_gaming-station' --format '{{.Names}}' | head -1)
  docker exec $CNAME ls /dev/input/
  ```
  Erwartung: `js0` und zugehörige `event*` sichtbar

- [ ] **3.5** In Steam Big Picture: Controller-Erkennung prüfen (Settings → Controller)

**Erfolgskriterium:** DS4 in Steam im Container sichtbar und als Gamepad erkannt.

---

## Phase 4: Container Lifecycle härten

**Ziel:** Gaming-Station Container soll nach externem Stop/Crash selbst wieder hochkommen.

**Kontext:** `RestartPolicy=no` → Container bleibt nach jedem Stop unten. Für diesen Betriebsmodus falsch.
In MODE=primary ist der Container komplett self-contained — kein Grund mehr für manuellen Neustart.

### Schritte

- [ ] **4.1** Blueprint `restart_policy` von `no` auf `unless-stopped` setzen
  - `unless-stopped`: startet nach Crash/Host-Reboot neu, stoppt nur bei explizitem `docker stop`

- [ ] **4.2** `stop_grace_period` auf `30s` erhöhen
  - Docker-Default (10s) zu kurz — Container wartet auf supervisord-Shutdown und udev

- [ ] **4.3** Testen: `docker stop $CNAME` → Container kommt selbst wieder hoch

**Erfolgskriterium:** Container überlebt `docker stop` und kommt ohne manuellen Eingriff wieder hoch.

---

## Phase 5: Performance Tuning ✅ ERLEDIGT (2026-03-25)

**Ziel:** Streaming-Qualität und 7DTD-Performance verbessern.

### Schritte

- [x] **5.1** Moonlight-Client: Bitrate auf `50 Mbps` senken — Empfehlung dokumentiert (Client-seitig)

- [x] **5.2** Moonlight: `Frame Pacing` ausschalten — Empfehlung dokumentiert (Client-seitig)

- [ ] **5.3** 7DTD Grafik-Preset senken (optional, wenn Spiel zu langsam):
  ```bash
  CNAME=$(docker ps --filter 'name=trion_gaming-station' --format '{{.Names}}' | head -1)
  docker exec $CNAME cat "/home/default/.local/share/unity3d/The Fun Pimps/7 Days To Die/prefs"
  ```
  Werte senken: `OptionsGfxQualityPreset 5→4`, `OptionsGfxViewDistance 6→4`, `OptionsGfxShadowQuality 3→2`

- [x] **5.4** Sunshine-Config optimiert:
  - `encoder = nvenc`, `hevc_mode = 2`, `fec_percentage = 0`
  - `nv_preset = llhq`, `nv_rc = cbr_hq`, `channels = 1`
  - `qos = disabled` (Docker-Bridge blockiert IP_TOS — verhindert sendmsg-Spam)
  - Config persistent unter `/data/services/gaming-station/config/sunshine/`

- [x] **5.5** nofile-Limit angehoben: Blueprint `ulimits: nofile: 65535` gesetzt

- [x] **5.6** Input-Fix: `apps.json` mit `xdotool windowfocus` für Desktop und Steam Big Picture

**Erfolgskriterium:** ✅ Stream mit NVENC/NvFBC/HEVC. ✅ nofile-Warnung behoben. Moonlight-Bitrate client-seitig noch zu reduzieren.

---

## Phase 6: TRION Chatflow Fix — conversation_mode

**Ziel:** TRION antwortet auf Smalltalk nicht mehr mit "kein Tool-Nachweis".

**Kontext:** Eigenständige Codebasis-Aufgabe, unabhängig von Gaming. Kann parallel oder danach gemacht werden.

**Codex-Doku:** `docs/obsidian/2026-03-22-container-commander-trion/08-TRION-Chatflow-Smalltalk-vs-Facts-Plan.md`

### Schritte (Kurzform)

- [ ] **6.1** Tests schreiben für: Smalltalk, Social Fact, Toolfrage, Mixed Turn
- [ ] **6.2** `conversation_mode`-Feld in Plan-Schema einführen (`core/orchestrator_plan_schema_utils.py`)
- [ ] **6.3** `core/orchestrator_conversation_mode_utils.py` neu anlegen mit Resolver-Logik
- [ ] **6.4** Grounding-Precheck in `output.py` an `conversation_mode` koppeln
- [ ] **6.5** Short-Input-Bypass in `orchestrator_sync_flow_utils.py` anpassen

**Erfolgskriterium:** `"guten Abend Trion wie geht es dir?"` bekommt eine kurze soziale Antwort, keinen Tool-Fallback.

---

## Schnell-Referenz: Was ist gerade kaputt? (Stand 2026-03-25)

| Problem | Ursache | Fix in Phase | Status |
|---|---|---|---|
| Moonlight pairt nicht | cert/pkey nicht explizit in Config | 1 | ✅ gelöst |
| X-Socket Restart-Loop | Host-Sunshine-Service | 2 | ✅ entfällt — Sunshine im Container |
| Controller verbindet nicht | BT noch nicht getestet in primary mode | 3 | offen |
| Container startet nicht selbst | RestartPolicy=no | 4 | offen |
| nofile-Limit zu niedrig (7DTD) | Container-ulimit default 1024 | 5 | ✅ gelöst — ulimit 65535 |
| Stream-Qualität | Bitrate/Preset noch nicht getunt | 5 | ✅ gelöst — NVENC/HEVC/llhq konfiguriert |
| sendmsg() failed: 13 Spam | IP_TOS auf Docker-Bridge geblockt | 5 | ✅ gelöst — qos=disabled |
| Maus/Tastatur ohne Fokus | Kein xdotool windowfocus beim Connect | 5 | ✅ gelöst — apps.json |
| TRION Smalltalk-Bug | conversation_mode fehlt | 6 | offen |

---

## Wo sind die wichtigen Dateien? (Stand 2026-03-25)

```
Sunshine (im Container — persistent gemountet):
  docker exec $CNAME cat /home/default/.config/sunshine/sunshine.log   ← Runtime-Log
  docker exec $CNAME cat /home/default/.config/sunshine/sunshine.conf  ← Config (persistent)
  /data/services/gaming-station/config/sunshine/                        ← Host-Pfad (persistent)
  Sunshine WebUI: https://<TRION_PUBLIC_HOST>:47990                     ← Pairing, Apps, Creds

Gaming Container (persistente Daten auf Host):
  /data/services/gaming-station/config/          ← Container /config (Steam-Games)
  /data/services/gaming-station/data/steam-home/ ← Container /home/default/.steam
  /data/services/gaming-station/data/userdata/   ← Container /home/default/.local/share
    └── 7DaysToDie/                              ← 7DTD Saves, EOS-Cache
    └── unity3d/The Fun Pimps/7 Days To Die/prefs ← 7DTD Grafik-Settings

Jarvis/Code:
  container_commander/mcp_tools.py               ← Blueprint-Logik (_ensure_gaming_station_blueprint)
  marketplace/packages/gaming-station/package.json ← v1.1.0, primary mode
  core/layers/output.py                          ← Grounding (Phase 6)
  core/orchestrator_sync_flow_utils.py           ← Short-Input (Phase 6)
```

Publish-Hinweis 2026-04-07: Absolute Host-Pfade und konkrete LAN-URLs wurden fuer das oeffentliche Repo auf portable Platzhalter reduziert.
