# Sunshine Pairing + Host-Session Gegencheck

> ⚠️ **ARCHIV — Stand 2026-03-24 (Host-Bridge-Ära)**
> Dieser Gegencheck bezieht sich auf die frühere Architektur mit Sunshine auf dem Host.
> Alle referenzierten Pfade (`~/.config/sunshine/`, `sunshine-host.service`, etc.) wurden
> am 2026-03-25 vollständig entfernt. Sunshine läuft jetzt im Container.
>
> Der Abschnitt **"Exakter GFE Pairing-Flow"** und die **Moonlight-Plist-Diagnose** bleiben
> als allgemeine Referenz wertvoll — der Pairing-Mechanismus ist unabhängig davon wo
> Sunshine läuft identisch.

Datum: 2026-03-24

Dieser Gegencheck verifiziert die Codex-Analyse vom selben Tag gegen Live-State und ergänzt eigenständige Befunde.

---

## Gegencheck der 4 Codex-Probleme

### Problem 1: Pairing scheitert serverseitig — BESTÄTIGT

**Beweis:**
- `~/.config/sunshine/sunshine_state.json` enthält nur Login-Credentials, keine `named_devices`
- WebUI ist erreichbar (Port 47990 TCP aktiv)
- `credentials/` enthält nur `cacert.pem` + `cakey.pem` — kein einziger Client-Cert

**Zusatzfund:**
Die Sunshine-Config liegt in `host-test/sunshine.conf`, aber State/Credentials liegen im Default-Pfad `~/.config/sunshine/`. Das ist gewollt, erzeugt aber einen diagnostischen Blindfleck: Sunshine-Logs gehen in `~/.local/state/sunshine-host.log` (Datei), nicht ins Journal. Pairing-Fehler tauchen dadurch **nicht** in `journalctl` auf.

---

### Problem 2: Host-Session-Instabilität — BESTÄTIGT + eigener Fund

**Beweis:**
Die Stopp-Kette ist: `systemd → startx → xinit → Xorg + openbox + sunshine`. Fragil an jedem Übergang.

**Zusatzfund (nicht in Codex-Analyse):**
Der `cleanup()` Trap in `host-sunshine-xsession.sh` killt nur `sunshine_pid` und `openbox_pid` — aber **nicht Xorg selbst**. Xorg wird von xinit/startx verwaltet. Wenn startx SIGTERM nicht sauber weitergibt oder Xorg zu langsam stirbt, bleibt `/tmp/.X11-unix/X0` als Socket-Datei liegen.

Folge: Nach einem unsauberen Stop scheitert der nächste Start mit `Display :0 already in use`. Das Service-File hat `Restart=always` ohne `StartLimitIntervalSec` — das kann in eine schnelle Restart-Schleife kippen sobald der X-Socket hängt.

Aktueller Zustand verifiziert: `/tmp/.X11-unix/X0` existiert (Service läuft, also normal), aber das Risiko gilt für jeden unsauberen Stop.

---

### Problem 3: Controller BT-Pfad — BESTÄTIGT mit Einschränkung

**Beweis:**
```
bluetoothctl info 58:10:31:39:50:06
  Paired: yes
  Trusted: yes
  Connected: no
```

**Einschränkung:**
Der neue USB-BT-Stick wurde gerade erst angeschlossen. Die `Authentication Failed (0x05)`-Fehler die Codex sah kamen vermutlich vom alten Adapter. Mit dem neuen Stick ist der Zustand noch offen — der DS4 wurde noch nicht versucht neu zu verbinden. Kein bestätigter Fehler, sondern offener Stand.

---

### Problem 4: Container-Crashes sind kein OOM — BESTÄTIGT

**Beweis:**
```
RestartPolicy: {'Name': 'no', 'MaximumRetryCount': 0}
OOMKilled: false
Status: running
```

Container läuft gerade. Kein OOM. Kein auto-restart. Alle Exits sind management-bedingt.

---

### Zusatzfund: UDP-Ports — kein Bug

Keine UDP-Listener im Idle-Zustand. Codex konnte das nicht einordnen.

**Einordnung:** Normal. Sunshine öffnet UDP-Ports (47998–48010) erst wenn ein Client aktiv streamt. Im Idle ist das korrekte Verhalten.

---

## Tiefenanalyse: Warum Pairing nicht persistiert

Drei unabhängige Ursachen, die zusammen das Pairing-Problem erklären.

### Ursache 1: Credentials-Reset am 23.03. um 03:10

```
~/.config/sunshine/credentials/
  cacert.pem   (notBefore=Mar 23 03:11:16 2026)
  cakey.pem

~/.config/sunshine/credentials.pre-reset.20260323T031025Z/
  ← Backup der alten Credentials
```

Auf dem neuen CA-Cert: `notBefore=Mar 23 03:11:16 2026` — eine Minute nach dem Backup-Timestamp. Das bedeutet:

- Vor dem 23.03. war Moonlight möglicherweise gepairt (mit altem CA)
- Um 03:10 wurden Credentials resettet → neues CA-Cert erzeugt
- Moonlights altes Client-Zertifikat wurde von der **alten** CA ausgestellt
- Sunshine kennt die alte CA nicht mehr → lehnt das alte Cert ab
- Moonlight zeigt das nicht klar als "neu pairen notwendig" — es scheitert still auf RTSP-Ebene
- `RTSP handshake failed: 60` ist die sichtbare Folge, nicht die Ursache

**Konsequenz:** Moonlight muss den `ubuntu`-Eintrag vollständig löschen (nicht nur trennen) und neu pairen.

---

### Ursache 2: `min_log_level = 2` macht den Pairing-Flow komplett unsichtbar

In `host-test/sunshine.conf`:
```
min_log_level = 2
```

Level 2 = nur WARNING und ERROR. Pairing-Events in Sunshine sind INFO (Level 1). Jeder Pairing-Versuch, jede PIN-Eingabe, jedes Accept/Reject — alles wird stumm geschluckt.

Der Log endet nach dem Start mit `Avahi service ubuntu successfully established.` und zeigt danach nichts mehr. Wir können aktuell **nicht sehen ob ein Pairing-Versuch überhaupt bei Sunshine ankommt**.

---

### Ursache 3: Kein Client-Cert in `credentials/` seit dem Reset

```
~/.config/sunshine/credentials/
  cacert.pem
  cakey.pem
  (kein client_*.pem, kein paired_*.pem)
```

Wenn Moonlight erfolgreich pairt, schreibt Sunshine ein Client-Cert in dieses Verzeichnis und trägt das Gerät in `sunshine_state.json` unter `named_devices` ein. Beides fehlt vollständig. Kein Pairing ist seit dem Reset abgeschlossen worden.

---

## Klarer Diagnose-Plan für Pairing

### Schritt 1: min_log_level temporär auf 0 setzen

In `~/.config/sunshine/host-test/sunshine.conf`:
```
min_log_level = 0
```

Sunshine neu starten. Dann Pairing-Versuch machen und Log live beobachten:
```bash
tail -f ~/.local/state/sunshine-host.log
```

Der Log muss jetzt zeigen ob die Pairing-Anfrage von Moonlight ankommt, ob der PIN-Exchange stattfindet und wo genau es abbricht.

### Schritt 2: Moonlight auf dem Mac komplett entkoppeln

Nicht nur "trennen" — den `ubuntu`-Eintrag in Moonlight vollständig entfernen. Moonlight cached das alte Cert und versucht es weiter zu verwenden.

### Schritt 3: Pairing-Erfolg verifizieren

Nach dem Pairing-Versuch prüfen:
```bash
ls ~/.config/sunshine/credentials/
cat ~/.config/sunshine/sunshine_state.json | python3 -m json.tool
```

Wenn Pairing erfolgreich: neues `client_*.pem` in `credentials/` + `named_devices`-Eintrag in state.json.

Wenn nicht: Log zeigt jetzt wo es scheitert.

### Schritt 4: min_log_level wieder auf 2 zurücksetzen

Nach erfolgreicher Diagnose wieder:
```
min_log_level = 2
```

---

## Offene Punkte nach diesem Check

1. **X-Socket-Absicherung beim Stop** — `cleanup()` in `host-sunshine-xsession.sh` muss Xorg-Socket-Cleanup berücksichtigen oder der Service braucht einen sauberen Stop-Mechanismus
2. **BT-Controller neu verbinden** — mit dem neuen USB-BT-Stick testen, ob `Connected: yes` stabil erreicht werden kann
3. ~~**Pairing-Diagnose**~~ — ✅ GELÖST (siehe unten)
4. **Container RestartPolicy** — für diesen Betriebsmodus nicht `no` verwenden

---

## Pairing-Lösung — 2026-03-24 (nachgetragen)

### Tatsächlicher Root Cause

Nicht der Credentials-Reset allein, sondern eine Kombination:

1. Sunshine v2025.923/924 generiert **kein** `cert.pem`/`key.pem` automatisch beim Start
2. Ohne explizite `cert`/`pkey`-Einträge in der Config ist Sunshines `getservercert`-Handler defekt: er empfängt die Anfrage, wartet auf PIN-Eingabe, aber die Antwort ist kryptografisch unbrauchbar weil kein kohärentes Zertifikat/Schlüssel-Paar geladen ist
3. Moonlight bekommt `plaincert` (hex-enkodiertes Server-Cert aus `conf_intern.servercert`) zurück, kann es nicht gegen den Signatur-Key validieren, sendet kein `clientchallenge` → `named_devices` bleibt leer

### Exakter GFE Pairing-Flow (dokumentiert für zukünftige Diagnosen)

```
1. GET /serverinfo           → PairStatus prüfen
2. GET /pair?phrase=getservercert  → Sunshine wartet auf PIN (async!)
   → Nach PIN: antwortet mit paired=1, plaincert=<hex(cacert.pem)>
3. GET /pair?clientchallenge=...   → AES-Challenge mit PIN-Key
4. GET /pair?serverchallengeresp=... → Moonlight prüft pairingsecret-Signatur
5. GET /pair?clientpairingsecret=... → Sunshine trägt Client in named_devices ein
6. GET /pair?phrase=pairchallenge (HTTPS:47984) → finaler Ack
```

`named_devices` wird erst in Schritt 5 befüllt. Wenn es leer bleibt → Problem in Schritt 2–4.

### Fix

In `~/.config/sunshine/host-test/sunshine.conf`:
```
cert = $HOME/.config/sunshine/credentials/cacert.pem
pkey = $HOME/.config/sunshine/credentials/cakey.pem
```

Sunshine auf v2025.924.154138 aktualisiert. Danach Moonlight-Host-Eintrag in Plist gelöscht und neu gepairt → Erfolg.

### Diagnosetipp für die Zukunft

Moonlight-Plist auf dem Mac: `~/Library/Preferences/com.moonlight-stream.Moonlight.plist`
- `hosts.N.srvcert` muss nach `getservercert` befüllt sein
- `hosts.N.srvcert` leer = Moonlight hat plaincert nicht gespeichert = Antwort war unbrauchbar

Moonlight-Logs (macOS): `~/Library/Logs/Moonlight Game Streaming/`
- Dort stehen Fehler wie `Server certificate invalid` oder `Pairing stage #N failed`

Publish-Hinweis 2026-04-07: Absolute Host-Pfade wurden auf `$HOME`-basierte Platzhalter reduziert. Zertifikat-/Key-Namen bleiben zur technischen Diagnose erhalten; private Inhalte waren nie in dieser Notiz enthalten.
