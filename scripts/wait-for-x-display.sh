#!/usr/bin/env bash
# Wait for an X display (lightdm autologin) before launching Chromium.
set -euo pipefail

SERVICE_USER_HOME="${SERVICE_USER_HOME:-${HOME:-/home/quickprint}}"
export DISPLAY="${DISPLAY:-:0}"

wait_for_x() {
  local max_wait=${1:-120}
  local i
  for ((i = 1; i <= max_wait; i++)); do
    if [[ -S "/tmp/.X11-unix/X${DISPLAY#:}" ]] 2>/dev/null; then
      return 0
    fi
    if command -v xdpyinfo >/dev/null 2>&1 && xdpyinfo >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

resolve_xauthority() {
  if [[ -n "${XAUTHORITY:-}" && -f "${XAUTHORITY}" ]]; then
    return 0
  fi
  local candidate="${SERVICE_USER_HOME}/.Xauthority"
  if [[ -f "$candidate" ]]; then
    export XAUTHORITY="$candidate"
    return 0
  fi
  local uid
  uid="$(id -u "$(basename "$SERVICE_USER_HOME")" 2>/dev/null || id -u)"
  local runtime="/run/user/${uid}/gdm/Xauthority"
  if [[ -f "$runtime" ]]; then
    export XAUTHORITY="$runtime"
    return 0
  fi
  export XAUTHORITY="${SERVICE_USER_HOME}/.Xauthority"
}

resolve_xauthority

if ! wait_for_x "${WAIT_FOR_X_SECONDS:-120}"; then
  echo "No X display on ${DISPLAY} after ${WAIT_FOR_X_SECONDS:-120}s." >&2
  echo "  Ensure lightdm is running: sudo systemctl enable --now lightdm" >&2
  echo "  Reboot after setup: sudo reboot" >&2
  exit 1
fi
