# Gaming Station GitHub Package Prep

Archivstatus: Gestoppt und archiviert am 2026-04-01.
Hinweis: Diese Paket-/Shop-Vorbereitung bleibt nur noch als historische Referenz fuer den archivierten `gaming-station`-Zweig erhalten.

## Ziel

Diese Notiz ist das Handoff für einen separaten GitHub-Repo-/Shop-Paketaufbau von `gaming-station`.

Zielbild:

- `plug-and-install` für Nutzer
- nicht fest im TRION-Core verdrahtet
- enthält alles Relevante für:
  - Blueprint
  - Host-Companion
  - Storage-Layout
  - TRION-Addon-Dokumente

## Was in GitHub gehören sollte

### 1. Das eigentliche Paket

Pfad im aktuellen Repo:

- [gaming-station package](<repo-root>/marketplace/packages/gaming-station)

Wichtige Inhalte:

- `package.json`
- `README.md`
- `host/bin/`
- `host/systemd-user/`
- `host/config/sunshine/`
- `host/etc/X11/`

Das ist der Kern des optionalen `composite_addon`.

### 2. Die TRION-Addon-Dokumente

Pfad im aktuellen Repo:

- [gaming-station addon docs](<repo-root>/intelligence_modules/container_addons/profiles/gaming-station)

Dateien:

- [00-profile.md](<repo-root>/intelligence_modules/container_addons/profiles/gaming-station/00-profile.md)
- [10-runtime.md](<repo-root>/intelligence_modules/container_addons/profiles/gaming-station/10-runtime.md)
- [20-diagnostics.md](<repo-root>/intelligence_modules/container_addons/profiles/gaming-station/20-diagnostics.md)
- [30-known-issues.md](<repo-root>/intelligence_modules/container_addons/profiles/gaming-station/30-known-issues.md)

Diese Dateien gehören mit ins Paket, damit `TRION shell` den Container nach Installation auch versteht.

### 3. Die generischen Addon-Dokumente, von denen gaming-station abhängt

Empfohlen mitzuliefern oder sauber als Abhängigkeit zu dokumentieren:

- [generic-linux](<repo-root>/intelligence_modules/container_addons/profiles/generic-linux/00-shell-basics.md)
- [runtime-supervisord](<repo-root>/intelligence_modules/container_addons/profiles/runtime-supervisord/10-supervisord.md)
- [headless-x11-novnc](<repo-root>/intelligence_modules/container_addons/profiles/headless-x11-novnc/10-headless-x11-novnc.md)
- [app-sunshine](<repo-root>/intelligence_modules/container_addons/profiles/apps-sunshine/20-sunshine.md)
- [app-steam-headless](<repo-root>/intelligence_modules/container_addons/profiles/apps-steam-headless/20-steam-headless.md)

Wenn das Paket wirklich unabhängig vom Hauptrepo installierbar sein soll, sollten diese Dateien mit in das Paket-Repo.

### 4. Bundle-/Catalog-Artefakte

Für den Shop-/Marketplace-Pfad braucht ihr zusätzlich:

- ein `bundle`
- optional ein kleines Catalog-Repo/Manifest, das auf dieses Bundle zeigt

Wichtig:

- das Bundle ist der installierbare Transport
- das Paketverzeichnis ist die Source of truth

## Was nicht in GitHub aus dem Live-System kopiert werden sollte

Diese Pfade sind nur materialisierte Laufzeitdateien und sollten nicht als Quelle benutzt werden:

- `$HOME/.config/systemd/user/sunshine-host.service`
- `$HOME/.local/bin/start-host-sunshine-session.sh`
- `$HOME/.local/bin/host-sunshine-xsession.sh`
- `$HOME/.local/bin/gaming-station-steam.sh`
- `/usr/local/bin/sunshine-host-prepare.sh`
- `/etc/X11/xorg.conf.d/90-sunshine-headless.conf`
- `/etc/X11/Xwrapper.config`
- `/etc/X11/edid/monitor-1080p.bin`

Diese Dateien werden aus dem Paket heraus auf den Host materialisiert. Sie sind **nicht** die Git-Quelle.

## Empfohlene GitHub-Repo-Struktur

```text
gaming-station-addon/
├── README.md
├── package.json
├── marketplace/
│   └── packages/
│       └── gaming-station/
│           ├── package.json
│           ├── README.md
│           └── host/
│               ├── bin/
│               ├── config/
│               ├── etc/
│               └── systemd-user/
├── container_addons/
│   ├── profiles/
│   │   ├── gaming-station/
│   │   ├── generic-linux/
│   │   ├── runtime-supervisord/
│   │   ├── headless-x11-novnc/
│   │   ├── apps-sunshine/
│   │   └── apps-steam-headless/
│   └── ADDON_SPEC.md
├── bundles/
│   └── gaming-station.trion-bundle.tar.gz
└── catalog/
    └── blueprints.json
```

## Minimaler Paketinhalt für Version 1

Wenn ihr klein anfangen wollt, reicht zuerst:

1. `marketplace/packages/gaming-station/`
2. `container_addons/profiles/gaming-station/`
3. die 5 generischen Addon-Profile
4. ein exportiertes Bundle
5. `README.md` mit Installationshinweisen

## Wichtige technische Hinweise für Claude Desktop

### Paketmodell

`gaming-station` ist kein normaler Einzel-Blueprint mehr, sondern ein `composite_addon`:

- Container-Blueprint
- Host-Companion
- Storage-Layout
- TRION-Knowledge-Pack

### Host-Sunshine

Wichtig:

- Sunshine läuft hostnah
- nicht im Container
- der Container ist nur die Steam-/App-Bridge

### Zugriffspfade

Im Paket sollten die Host-Zugänge als Metadaten mit drin bleiben:

- `47990` → Sunshine Web UI

### Addon-Dokumente

Die Markdown-Dateien sind Teil des eigentlichen Produkts, nicht nur Dev-Doku.

Ohne sie fehlt `TRION shell` das container-spezifische Wissen.

## Wichtige aktuelle Repo-Dateien als Referenz

Core-/Integrationscode:

- [marketplace.py](<repo-root>/container_commander/marketplace.py)
- [host_companions.py](<repo-root>/container_commander/host_companions.py)
- [engine.py](<repo-root>/container_commander/engine.py)
- [storage-host-helper app.py](<repo-root>/mcp-servers/storage-host-helper/app.py)

Paketquellen:

- [gaming-station package](<repo-root>/marketplace/packages/gaming-station)
- [gaming-station shadow package](<repo-root>/marketplace/packages/gaming-station-shadow)

TRION-Wissen:

- [container_addons README](<repo-root>/intelligence_modules/container_addons/README.md)
- [ADDON_SPEC.md](<repo-root>/intelligence_modules/container_addons/ADDON_SPEC.md)
- [gaming-station profile docs](<repo-root>/intelligence_modules/container_addons/profiles/gaming-station)

## Status

Bereits geschafft:

- `composite_addon`-Bundle-Support
- Host-Companion-Materialisierung
- `binary_bootstrap` für Sunshine
- `host_packages.apt` fuer Host-Abhaengigkeiten wie `openbox`
- sicherer `shadow install`
- lokaler Shadow-Marketplace-Install erfolgreich
- Bundle-Roundtrip-Bug im Export gefixt
- `container_addons` werden jetzt zusammen mit dem Paket aus dem Bundle exportiert und beim Import wieder in `intelligence_modules/container_addons/...` installiert
- das Paketmanifest von `gaming-station` deklariert diese Addons jetzt explizit unter `container_addons`
- der bestehende Marketplace-/Installer-Pfad bleibt dabei bewusst `bundle_url`-basiert; `package_url` wird nur additiv mitnormalisiert
- der echte GitHub-Pfad `sync_remote_catalog(...) -> install_catalog_blueprint("gaming-station")` läuft jetzt erfolgreich durch
- Bundle-Addons werden dabei nicht mehr in den read-only Codepfad geschrieben, sondern in ein Runtime-Overlay unter `/app/data/marketplace/container_addons`
- der Loader liest dieses Overlay zusätzlich zum normalen Repo-Stand
- der lokale Host-Companion-Lifecycle ist jetzt vorhanden:
  - `ensure`
  - `check`
  - `repair`
  - `uninstall`
- diese Aktionen sind lokal auch schon über Commander-API und Commander-Frontend verdrahtet

Noch offen:

- neuesten GitHub-/Bundle-Stand erneut in den Runtime-Marketplace importieren, damit Felder wie `host_packages.apt = ["openbox"]` auch im laufenden Paketstore liegen
- Paketmodell bei Bedarf weiter für zusätzliche Host-Pakete verallgemeinern
- UI-Workflows für `check / repair / uninstall` weiter polieren

## Empfehlung für den nächsten Schritt mit Claude Desktop

1. Diese Repo-Struktur als separates Addon-Repo anlegen.
2. `marketplace/packages/gaming-station/` als Source of truth übernehmen.
3. `container_addons/profiles/...` mit übernehmen.
4. `README.md` für Nutzer schreiben:
   - Voraussetzungen
   - NVIDIA
   - Host-Sunshine
   - Storage
   - Install / Deploy
5. Danach erst den Catalog-/Bundle-Pfad veröffentlichen.

## Neuer Installer-Stand

Der relevante TRION-Core-Stand ist jetzt:

- [marketplace.py](<repo-root>/container_commander/marketplace.py)
- [gaming-station package.json](<repo-root>/marketplace/packages/gaming-station/package.json)

Wichtige Wirkung:

- `export_bundle("gaming-station")` legt jetzt zusätzlich `container_addons/...` in das `.trion-bundle.tar.gz`
- `import_bundle(...)` installiert diese Addons wieder in den echten TRION-Addon-Pfad
- generische und spezialisierte `gaming-station`-Markdowns reisen damit zusammen mit dem Paket
- im laufenden Admin-API-Container landen sie zur Laufzeit jetzt unter:
  - `/app/data/marketplace/container_addons`
- der Loader ergänzt diesen Runtime-Pfad über dem read-only Repo-Stand

Live verifiziert wurde bereits, dass das exportierte Bundle jetzt enthält:

- `package.json`
- `container_addons/profiles/gaming-station/...`
- `container_addons/profiles/generic-linux/...`
- `container_addons/profiles/runtime-supervisord/...`
- `container_addons/profiles/headless-x11-novnc/...`
- `container_addons/profiles/apps-sunshine/...`
- `container_addons/profiles/apps-steam-headless/...`
- `container_addons/ADDON_SPEC.md`
- `container_addons/README.md`

Zusätzlich live verifiziert:

- `sync_remote_catalog(repo_url="https://github.com/danny094/TRION-blueprints")` erkennt `gaming-station`
- `install_catalog_blueprint("gaming-station", overwrite=True)` liefert `imported: True`
- Paket wird installiert nach:
  - `/app/data/marketplace/packages/gaming-station`
- Runtime-Addons werden installiert nach:
  - `/app/data/marketplace/container_addons`
