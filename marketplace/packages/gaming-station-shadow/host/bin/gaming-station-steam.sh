#!/usr/bin/env bash
set -euo pipefail

action="${1:-open-bigpicture}"
container_id="$(docker ps --filter 'name=trion_gaming-station' --format '{{.ID}}' | head -n1)"

if [[ -z "${container_id}" ]]; then
  echo "gaming-station container not running" >&2
  exit 1
fi

normalize_bigpicture_window() {
  stable_hits=0
  i=0
  while [ "$i" -lt 40 ]; do
    result="$(
      docker exec -u default "${container_id}" env DISPLAY=:0 HOME=/home/default sh -lc '
        best_id=""
        best_area=0
        best_width=0
        best_height=0
        for id in $(xdotool search --classname steamwebhelper 2>/dev/null || true); do
          name="$(xdotool getwindowname "$id" 2>/dev/null || true)"
          [ "$name" = "Steam" ] || continue
          eval "$(xdotool getwindowgeometry --shell "$id" 2>/dev/null || true)"
          area=$(( ${WIDTH:-0} * ${HEIGHT:-0} ))
          if [ "$area" -gt "$best_area" ]; then
            best_area="$area"
            best_id="$id"
            best_width="${WIDTH:-0}"
            best_height="${HEIGHT:-0}"
          fi
        done
        if [ -z "$best_id" ]; then
          best_id="$(xdotool search --name "Steam Big Picture Mode" 2>/dev/null | head -n1 || true)"
          if [ -n "$best_id" ]; then
            eval "$(xdotool getwindowgeometry --shell "$best_id" 2>/dev/null || true)"
            best_width="${WIDTH:-0}"
            best_height="${HEIGHT:-0}"
          fi
        fi
        printf "%s|%s|%s" "$best_id" "${best_width:-0}" "${best_height:-0}"
      '
    )"
    IFS='|' read -r win width height <<< "${result}"
    if [ -n "${win}" ]; then
      docker exec -u default "${container_id}" env DISPLAY=:0 HOME=/home/default TARGET_WIN="$win" sh -lc '
        xdotool windowactivate "$TARGET_WIN" 2>/dev/null || true
        xdotool windowraise "$TARGET_WIN" 2>/dev/null || true
        xdotool windowmove "$TARGET_WIN" 0 0 2>/dev/null || true
        xdotool windowsize "$TARGET_WIN" 1920 1080 2>/dev/null || true
      '
      if [ "${width:-0}" = "1920" ] && [ "${height:-0}" = "1080" ]; then
        stable_hits=$((stable_hits + 1))
        if [ "$stable_hits" -ge 3 ]; then
          return 0
        fi
      else
        stable_hits=0
      fi
    fi
    i=$((i + 1))
    sleep 0.5
  done
  return 0
}

case "${action}" in
  open-bigpicture)
    docker exec -u default "${container_id}" env DISPLAY=:0 HOME=/home/default \
      /home/default/.steam/ubuntu12_32/steam steam://open/bigpicture
    normalize_bigpicture_window
    ;;
  ensure-bigpicture-window)
    normalize_bigpicture_window
    ;;
  close-bigpicture)
    exec docker exec -u default "${container_id}" env DISPLAY=:0 HOME=/home/default \
      /home/default/.steam/ubuntu12_32/steam steam://close/bigpicture
    ;;
  *)
    echo "unknown action: ${action}" >&2
    exit 2
    ;;
esac
