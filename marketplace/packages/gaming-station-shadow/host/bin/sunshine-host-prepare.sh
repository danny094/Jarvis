#!/usr/bin/env bash
set -euo pipefail

modprobe uinput 2>/dev/null || true

if ! pgrep -f '/usr/lib/xorg/Xorg .*:0' >/dev/null 2>&1; then
  rm -f /tmp/.X0-lock /tmp/.X11-unix/X0 2>/dev/null || true
fi

if [ -e /dev/uinput ]; then
  chown danny:danny /dev/uinput || true
  chmod 660 /dev/uinput || true
fi

if [ -e /dev/dri/card0 ]; then
  chgrp video /dev/dri/card0 || true
  chmod 660 /dev/dri/card0 || true
fi

if [ -e /dev/dri/renderD128 ]; then
  if getent group render >/dev/null 2>&1; then
    chgrp render /dev/dri/renderD128 || true
  else
    chgrp video /dev/dri/renderD128 || true
  fi
  chmod 660 /dev/dri/renderD128 || true
fi
