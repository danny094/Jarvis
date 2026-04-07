#!/usr/bin/env bash
set -euo pipefail

export DISPLAY="${DISPLAY:-:0}"
export XDG_SESSION_TYPE=x11
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-}"

ensure_sunshine_bin() {
  local target url tmp

  target="${HOME}/.local/opt/sunshine/sunshine.AppImage"
  url="https://github.com/LizardByte/Sunshine/releases/latest/download/sunshine.AppImage"

  mkdir -p "$(dirname "${target}")"

  if [[ -x "${target}" ]]; then
    printf '%s\n' "${target}"
    return 0
  fi

  tmp="${target}.download.$$"
  if command -v curl >/dev/null 2>&1; then
    curl -LfsS "${url}" -o "${tmp}"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "${tmp}" "${url}"
  else
    echo "Neither curl nor wget is available to download Sunshine AppImage" >&2
    return 1
  fi

  chmod 0755 "${tmp}"
  mv -f "${tmp}" "${target}"
  printf '%s\n' "${target}"
}

if [[ -n "${SUNSHINE_BIN:-}" ]]; then
  sunshine_bin="${SUNSHINE_BIN}"
elif command -v sunshine >/dev/null 2>&1; then
  sunshine_bin="$(command -v sunshine)"
else
  sunshine_bin="${HOME}/.local/opt/sunshine/sunshine.AppImage"
fi

if [[ ! -x "${sunshine_bin}" ]]; then
  if command -v sunshine >/dev/null 2>&1; then
    sunshine_bin="$(command -v sunshine)"
  else
    sunshine_bin="$(ensure_sunshine_bin)"
  fi
fi

xhost +local: >/dev/null 2>&1 || true

xrandr --output {{XRANDR_OUTPUT_NAME}} --mode 1920x1080 >/dev/null 2>&1 || true

if command -v openbox >/dev/null 2>&1; then
  openbox --sm-disable >/dev/null 2>&1 &
  openbox_pid=$!
else
  openbox_pid=""
fi

mkdir -p "$(dirname "{{SUNSHINE_CONFIG_PATH}}")" "$(dirname "{{SUNSHINE_LOG_PATH}}")"

"${sunshine_bin}" "{{SUNSHINE_CONFIG_PATH}}" \
  >"{{SUNSHINE_LOG_PATH}}" 2>&1 &
sunshine_pid=$!

cleanup() {
  kill "${sunshine_pid}" 2>/dev/null || true
  if [[ -n "${openbox_pid:-}" ]]; then
    kill "${openbox_pid}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

xsetroot -solid "#101418" >/dev/null 2>&1 || true

wait "${sunshine_pid}"
