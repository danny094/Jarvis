#!/usr/bin/env bash
set -euo pipefail

action="${1:-open-bigpicture}"
container_id="$(docker ps --filter 'name=trion_gaming-station' --format '{{.ID}}' | head -n1)"

if [[ -z "${container_id}" ]]; then
  echo "gaming-station container not running" >&2
  exit 1
fi

steam_is_running() {
  docker exec -u default "${container_id}" env HOME=/home/default sh -lc '
    pgrep -f "/home/default/.steam/ubuntu12_32/steam" >/dev/null 2>&1
  '
}

forward_steam_uri() {
  local uri="$1"
  if steam_is_running; then
    docker exec -u default "${container_id}" env DISPLAY=:0 HOME=/home/default \
      /home/default/.steam/ubuntu12_32/steam "${uri}"
    return 0
  fi

  docker exec -u default "${container_id}" env DISPLAY=:0 HOME=/home/default bash -lc "
    nohup /home/default/.steam/steam.sh '${uri}' >/tmp/gaming-station-steam-helper.log 2>&1 &
  "
}

normalize_bigpicture_window() {
  # Passive now: fullscreen is handled by host Openbox/Xorg.
  return 0
}

game_window_present() {
  docker exec -u default "${container_id}" env DISPLAY=:0 HOME=/home/default sh -lc '
    wmctrl -lx 2>/dev/null | awk '"'"'
      $3 !~ /^steamwebhelper\.steam$/ && $5 != "Steam" && $5 != "Big-Picture-Modus" && $5 != "Steam" { found=1 }
      END { exit(found ? 0 : 1) }
    '"'"'
  '
}

case "${action}" in
  open-bigpicture)
    if game_window_present; then
      exit 0
    fi
    forward_steam_uri "steam://open/bigpicture"
    normalize_bigpicture_window
    ;;
  ensure-bigpicture-window)
    normalize_bigpicture_window
    ;;
  close-bigpicture)
    exec docker exec -u default "${container_id}" env DISPLAY=:0 HOME=/home/default bash -lc '
      if pgrep -f "/home/default/.steam/ubuntu12_32/steam" >/dev/null 2>&1; then
        exec /home/default/.steam/ubuntu12_32/steam steam://close/bigpicture
      fi
      exit 0
    '
    ;;
  *)
    echo "unknown action: ${action}" >&2
    exit 2
    ;;
esac
