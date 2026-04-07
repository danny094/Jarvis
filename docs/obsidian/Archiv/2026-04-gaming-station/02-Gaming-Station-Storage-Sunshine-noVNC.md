# Gaming Station, Storage, Sunshine, noVNC

Archivstatus: Gestoppt und archiviert am 2026-04-01.
Hinweis: Diese Notiz dokumentiert einen frueheren `gaming-station`-Zwischenstand und ist nicht mehr Teil eines aktiven Arbeitspfads.

## Aktueller Prioritätswechsel

Stand: 2026-03-26

Der aktuelle Fokus liegt **nicht** mehr auf weiterem punktuellem Sonderfall-Patching im `gaming-station`-Container, sondern zuerst auf dem neuen generischen `runtime_hardware`-Modul als eigenem installierbaren Service.

Bezug:

- [[23-Runtime-Hardware-Modul-Implementationsplan]]
- [[24-Runtime-Hardware-v0-Installationsvertrag]]

Warum dieser Wechsel sinnvoll ist:

- das verbleibende Maus-/Tastatur-/Controller-Thema zeigt, dass Jarvis bisher keine saubere generische Hardware- und Attachment-Schicht hat
- ein eigenes `runtime_hardware`-Modul schafft zuerst die fehlende Grundlage fuer:
  - sichtbare Hardware-Inventarisierung
  - strukturierte Auswahl verfuegbarer Input-/USB-/Device-Ressourcen
  - formale Entscheidung `live attach` vs. `requires restart/recreate`
  - spaetere Wiederverwendung fuer `container`, `qemu` und weitere Connectoren
- genau das hilft spaeter auch `gaming-station`, weil Controller, Input-Geraete und andere Hardware nicht mehr ueber Einzelfall-Workarounds, sondern ueber einen systematischen Pfad modelliert werden

Wichtig:

- das neue Modul loest den aktuellen Sunshine-/Xorg-/Input-Bug nicht automatisch sofort
- es ist aber sehr wahrscheinlich die sauberere Grundlage, um genau solche Hardware- und Passthrough-Probleme spaeter gezielt und reproduzierbar zu loesen

## Ziel

`gaming-station` wurde als realer Testfall gewählt, um StorageBroker und Container Commander enger zusammenzubringen. Der Container basiert auf `Steam Headless + Sunshine` und ist deutlich realistischer als ein synthetischer Test.

## Warum nicht Batocera

Batocera wurde kurz erwogen, aber verworfen. Für den Commander war `Steam Headless` die pragmatischere Option:

- Docker-näher
- besser für echten Containerbetrieb geeignet
- sinnvoll für Sunshine-/Streaming-Szenarien
- gut geeignet als Integrations- und Storage-Test

## StorageBroker-Integration

Ziel war, die externe 1TB-Platte mit der 500GB-Partition nicht nur manuell zu mounten, sondern den Pfad sauber für Commander und später TRION nutzbar zu machen.

Erreicht:

- externer Storage wurde als Managed Base für den StorageBroker nutzbar gemacht
- `gaming-station` bekam eigene Service-Pfade unter `/data/services/gaming-station`
- der Blueprint nutzt nun Host-Pfade/Assets statt anonymer Docker-Volumes
- dadurch landen große Daten wie Spielebibliothek auf der externen Platte

Wichtiger Architekturpunkt:

- StorageBroker soll generisch bleiben
- Commander soll mit Scopes/Assets arbeiten
- TRION soll später dieselben freigegebenen Pfade nutzen können, ohne rohe Host-Pfade zu kennen

## Gaming-Container

Der `gaming-station`-Blueprint wurde für den realen Betrieb gehärtet:

- `Steam Headless`-Image
- Sunshine-Ports veröffentlicht
- `ipc_mode="host"`
- Headless-X11-Anpassungen
- Healthcheck auf den passenden Sunshine-Port mit längerer Warmup-Zeit

## Sunshine

Wichtige Erkenntnisse:

- Sunshine-WebUI läuft auf `47990`
- Zugriff nur per `https://...:47990/`
- self-signed Zertifikat muss im Browser bestätigt werden

Die erste Container-Variante hatte aber ein NVIDIA-/Output-Problem:

- WebUI erreichbar heißt nicht automatisch, dass Capture/Encoder sauber funktionieren
- Container-Sunshine scheiterte auf NVIDIA am echten Capture-/Output-Pfad
- noVNC und Sunshine wollten am Ende nicht sauber denselben Container-Displaypfad teilen

Deshalb wurde die Architektur später umgestellt:

- Sunshine läuft jetzt **hostnah**
- der Host hält `Xorg :0`, Capture und NVENC
- `gaming-station` rendert als Host-Bridge-Container auf den Host-Xorg
- Steam bleibt im Container, Streaming liegt beim Host

Wichtige Folge:

- Moonlight funktioniert damit stabiler als mit Sunshine im Container
- noVNC ist nicht mehr der eigentliche Gaming-Stream-Pfad, sondern ein separater Debug-/GUI-Pfad

## noVNC

Für `gaming-station` wurde zusätzlich eine sichtbare Desktop-GUI herausgeführt:

- noVNC veröffentlicht auf Host-Port `47991`
- Commander zeigt `Open Desktop GUI`
- der Link öffnet die virtuelle Desktop-Sitzung in einem neuen Tab

Damit ist die GUI im headless Container nicht mehr nur indirekt per `xdotool` erreichbar, sondern auch sichtbar.

Wichtige spätere Erkenntnis:

- noVNC war als Debug-Desktop nützlich, aber nicht der richtige Weg für den eigentlichen Moonlight-Stream
- ein separater virtueller noVNC-Desktop löst Sichtbarkeit, aber nicht automatisch Sunshine-Capture auf NVIDIA

## Host-Bridge-Stand

Nach der Umstellung auf hostnahes Sunshine gilt für `gaming-station`:

- Host-Sunshine streamt den Host-Xorg `:0`
- `gaming-station` läuft als Host-Display-Bridge
- Steam wird im Container gehalten, aber auf dem Host-Display gezeigt
- Sunshine-App `Steam Big Picture` startet Container-Steam statt Host-Steam

Zusätzliche Härtung:

- Host-Auflösung und Sunshine-App-Profil wurden auf `1920x1080` vereinheitlicht
- ein früheres `1920x1200`-Mismatch wurde entfernt
- Big Picture wurde per Helper auf ein echtes `1920x1080`-Fenster gezogen, weil Steam zunächst nur als `1280x800`-Fenster lief
- der Big-Picture-Helper wurde später weiter gehärtet, damit das sichtbare Steam-Fenster nicht nur einmal, sondern über mehrere Polls auf `1920x1080` stabilisiert wird
- in der Praxis wurde der Fehler reproduziert, das Fenster absichtlich wieder auf `1280x800` verkleinert und anschließend automatisch wieder auf `1920x1080` gezogen
- für den finalen GitHub-deployten Stand war zusätzlich ein kleiner Host-Window-Manager noetig:
  - `openbox --sm-disable`
  - ohne Window Manager blieb Big Picture trotz korrektem Containerstart wieder als `1280x800`-Fenster haengen
  - mit `openbox` erschien `Steam Big Picture Mode` auf dem Host wieder als echtes `1920x1080+0+0`

## Streaming-Qualität

Nach dem Host-Bridge-Umbau gab es noch zwei wichtige Qualitätsfehler:

- Sessions konnten zunächst mit sehr niedriger Bitrate und `H.264` starten
- das sichtbare Steam-Fenster lief nur als kleiner `1280x800`-Bereich statt fullscreen

Späterer Stand:

- Moonlight wurde auf höhere Bitrate und `HEVC` umgestellt
- Sunshine-Logs zeigten danach den `hevc_nvenc`-Pfad
- der sichtbare Steam-Frame wurde auf `1920x1080` stabilisiert
- das Stream-Bild war danach korrekt groß und sauber
- spaeter zeigte sich aber auch:
  - fuer `1080p` kann eine sehr hohe Moonlight-Bitrate wie `150 Mbps` bereits unnötig hoch sein
  - das Spiel selbst kann intern sauber mit knapp `60 FPS` laufen, waehrend sich der Stream trotzdem noch traeger anfuehlt

Wichtige praktische Erkenntnis:

- schlechte Bildqualität war hier nicht nur eine reine Netzwerkfrage
- ein Teil der “matschigen” Darstellung kam direkt vom falschen Fenster-/Auflösungszustand
- der andere Teil kam vom Client-seitig zu niedrig ausgehandelten Codec-/Bitrate-Pfad
- spaeter blieb als Restthema eher Streaming-/Frametime-Reibung uebrig, nicht mehr der eigentliche Spielstart

Aktueller Sunshine-Stand:

- aktiver Config-Pfad:
  - `$HOME/.config/sunshine/host-test/sunshine.conf`
- aktiver Encoder-Pfad:
  - `hevc_nvenc`
- kleine LAN-Haertung:
  - `fec_percentage = 0`
  - `min_log_level = 2`

## Input / Controller

Der Host-Bridge-Pfad wurde auch auf Eingabe geprüft:

- Host-Sunshine arbeitet mit `/dev/uinput`
- `gaming-station` sieht im Container zusätzlich echte `/dev/input`-Geräte
- im Container waren unter anderem sichtbar:
  - `js0`
  - `event*`
- der User `default` ist in den relevanten Gruppen:
  - `input`
  - `sgx`
  - `audio`
  - `video`
  - `render`

Aktuelle Einschätzung:

- Maus/Tastatur sollten sauber funktionieren
- echter Controller-Input ist sehr wahrscheinlich ebenfalls nativ möglich
- der verbleibende offene Punkt ist nur noch der praktische End-to-End-Test in Steam selbst

Ergaenzung vom 2026-03-26:

- Diese Einschaetzung war fuer den damaligen Host-Bridge-Stand plausibel, ist aber nicht mehr die alleinige Prioritaet.
- Der naechste strategische Schritt ist jetzt zuerst das generische `runtime_hardware`-Modul.
- `gaming-station` bleibt danach der erste reale Testfall fuer:
  - `input`
  - `usb`
  - Controller-/Device-Zuordnung
  - spaeter auch storage-nahe Hardware-Referenzen

## Persistenz beim Stop

`gaming-station` wird im Commander jetzt als zu erhaltender Service behandelt:

- normaler `stop` löscht den Container nicht
- `start` kann denselben gestoppten Container wieder hochfahren
- das passt besser zu Steam-/Home-/Session-State als ein ephemeres Stop+Remove-Verhalten

Wichtige spätere Erkenntnis:

- `stop != delete` allein war noch nicht genug
- ein älterer `primary`-Container konnte trotzdem in einen falschen Steam-Bootstrap-Zustand laufen
- der eigentliche stabile Fix war:
  - neuer Host-Bridge-Container statt alter Container-Generation
  - persistentes Steam-Home unter `/data/services/gaming-station/data/steam-home`
  - verifizierter `stop -> start`-Pfad ohne erneuten Debian-/`zenity`-Installer

## Steam-State und Image-Generationen

Beim Debugging zeigte sich ein wichtiger Strukturfehler:

- der gespeicherte Blueprint war bereits `host-bridge`
- ein erhaltener alter Container lief aber noch als frühere `primary`-Generation weiter
- dadurch sah es so aus, als ob `gaming-station` "denselben" Stand neu startet, obwohl in Wahrheit alter Container und neuer Blueprint nicht mehr zusammenpassten

Zur Härtung wurde deshalb ergänzt:

- Dockerfile-basierte Blueprint-Images werden nicht mehr nur als statisches `latest` behandelt
- `gaming-station` bekommt jetzt content-basierte lokale Image-Tags
- laufende Container tragen zusätzlich das Label `trion.image_tag`

Zusätzlicher Persistenz-Fix:

- `/home/default/.steam` wird im Host-Bridge-Profil explizit auf
  `/data/services/gaming-station/data/steam-home`
  gebunden
- dadurch bleiben nicht nur Library-Ordner, sondern auch die echten Steam-Binaries und Runtime-Dateien erhalten
- genau das verhindert, dass Debian `steam` nach einem Neustart wieder in den Installerpfad fällt

## Aktueller Nutzen

- echter Gaming-/Desktop-Testcontainer im Commander
- externer Storage ist im End-to-End-Pfad berücksichtigt
- Sunshine-WebUI, Moonlight und noVNC sind getrennt nutzbar
- sehr guter Referenzfall für weitere Container- und Storage-Integrationen

## Composite Addon / Marketplace

Der nächste Architektur-Schritt ist, `gaming-station` nicht fest in TRION-Core zu verdrahten, sondern als optionales `composite addon` auszuliefern.

Das Paket umfasst dann gemeinsam:

- den Container-Blueprint
- den Host-Companion für Sunshine/Xorg/uinput
- die Storage-Struktur für `config`, `data` und `steam-home`
- einen Binary-Bootstrap für `sunshine`, falls `/usr/bin/sunshine` auf dem Host fehlt

Wichtige Konsequenz:

- Nutzer installieren `gaming-station` nur dann, wenn sie es wirklich wollen
- der TRION-Core bleibt schlanker
- Host-spezifische Gaming-Dateien sind sauber vom Core getrennt
- Fresh-Install und Repair werden später deutlich reproduzierbarer
- ein verbleibender Paket-Restpunkt ist dabei noch:
  - die Host-Abhaengigkeit `openbox` muss noch sauber in den Addon-/Installer-Pfad aufgenommen werden

## Shadow Install

Für den Host-Companion gibt es jetzt zusätzlich einen sicheren `shadow install`-Pfad:

- Paket-ID: `gaming-station-shadow`
- eigener Service:
  - `sunshine-host-shadow.service`
- eigene Config-Pfade unter:
  - `~/.config/sunshine-shadow/...`
- eigene Helper-Skripte mit `-shadow`-Namen

Ziel:

- Host-Dateien materialisieren
- Ownership prüfen
- Service-Dateien validieren
- den laufenden echten `sunshine-host.service` dabei nicht anfassen

Live verifiziert:

- `sunshine-host.service` blieb `active` und `enabled`
- `sunshine-host-shadow.service` blieb `inactive` und `disabled`
- Home-Dateien des Shadow-Install-Pfads landen korrekt als `danny:danny`
- System-Dateien unter `/etc/...` und `/usr/local/bin/...` bleiben korrekt `root:root`

## Wichtige Hinweise für andere Nutzer

Wenn andere Nutzer `gaming-station` auf ihrem System lauffähig bekommen wollen, sind diese Punkte wichtig:

- `NVIDIA + Sunshine im Container` ist nicht automatisch der beste Weg. In diesem Projekt war der stabile Pfad am Ende:
  - `Steam im Container`
  - `Sunshine auf dem Host`
- noVNC ist nützlich für Installer, Debugging und Sichtbarkeit, aber nicht automatisch der richtige Pfad für den eigentlichen Gaming-Stream.
- Der Host sollte für TV-/Moonlight-Nutzung auf einem sauberen `16:9`-Modus laufen, idealerweise `1920x1080`. Ein Modus wie `1920x1200` kann sofort zu kleinen oder letterboxed Steam-Oberflächen führen.
- Steam Big Picture startet nicht immer wirklich fullscreen. Es kann nötig sein, das Fenster aktiv auf `1920x1080` zu ziehen.
- Große Daten wie die Steam-Library sollten auf persistentem Storage wie `/data` liegen, nicht nur im Container-Dateisystem.
- Ein Gaming-Service sollte beim normalen `Stop` erhalten bleiben. `Stop != Delete` ist für Steam-/Home-/Session-State deutlich sinnvoller.
- Der erste Start kann durch Installer, Runtime-Bootstrap und Steam-Login träge wirken. Das ist nicht automatisch ein Fehler im Commander oder Container.
- Pairing und Streaming-Verhalten können versionsabhängig sein. Wenn Sunshine/Moonlight komisch reagiert, lohnt sich ein Gegencheck mit einem anderen offiziellen Sunshine-Build.

## Pragmatische Voraussetzungen

Für andere Nutzer ist diese Reihenfolge am sinnvollsten:

1. Persistenten Storage für `/data` vorbereiten.
2. Host-Displaypfad sauber aufsetzen.
3. Host-Sunshine funktionsfähig bekommen.
4. Erst danach `gaming-station` als Host-Bridge-Container anbinden.
5. noVNC als Debugpfad betrachten, nicht als Haupt-Streaming-Lösung.
