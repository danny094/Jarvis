#!/usr/bin/env bash
set -euo pipefail

export DISPLAY="${DISPLAY:-:0}"
export XDG_SESSION_TYPE=x11
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-}"

if [[ -n "${SUNSHINE_BIN:-}" ]]; then
  sunshine_bin="${SUNSHINE_BIN}"
elif command -v sunshine >/dev/null 2>&1; then
  sunshine_bin="$(command -v sunshine)"
else
  sunshine_bin="${HOME}/.local/opt/sunshine/sunshine.AppImage"
fi

xhost +local: >/dev/null 2>&1 || true

xrandr --output {{XRANDR_OUTPUT_NAME}} --mode 1920x1080 >/dev/null 2>&1 || true

mkdir -p "$(dirname "{{SUNSHINE_CONFIG_PATH}}")" "$(dirname "{{SUNSHINE_LOG_PATH}}")"

"${sunshine_bin}" "{{SUNSHINE_CONFIG_PATH}}" \
  >"{{SUNSHINE_LOG_PATH}}" 2>&1 &
sunshine_pid=$!

cleanup() {
  kill "${sunshine_pid}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

xsetroot -solid "#101418" >/dev/null 2>&1 || true

wait "${sunshine_pid}"
