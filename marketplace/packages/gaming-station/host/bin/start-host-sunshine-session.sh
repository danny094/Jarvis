#!/usr/bin/env bash
set -euo pipefail

cat <<'MSG'
Starte eine hostseitige X11-Session auf :0 und darin Sunshine.
Wichtig: Dieses Skript sollte aus einer echten TTY-Sitzung gestartet werden, nicht aus einem bereits laufenden X-Terminal.
Beispiel:
  1. Auf dem Host zu TTY2 wechseln
  2. Login als danny
  3. ~/.local/bin/start-host-sunshine-session.sh
MSG

sudo {{HOST_PREP_SCRIPT_PATH}}

exec startx "{{HOST_XSESSION_SCRIPT_PATH}}" -- :0 -nolisten tcp
