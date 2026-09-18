#!/usr/bin/env bash
# Remove QuickPrint systemd integration installed by scripts/setup_pi.sh.
# Preserves repository data, .env files, jobs, logs, and CUPS printers.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/install-common.sh
source "${SCRIPT_DIR}/lib/install-common.sh"

PURGE_DISPLAY=0
for arg in "$@"; do
  case "$arg" in
    --purge-display) PURGE_DISPLAY=1 ;;
    -h|--help)
      cat <<EOF
Usage: sudo ${SCRIPT_DIR}/uninstall_pi.sh [--purge-display]

Removes:
  - quickprint-agent.service (stop, disable, delete unit)
  - quickprint-display.service (stop, disable, delete unit)

With --purge-display also removes:
  - /etc/lightdm/lightdm.conf.d/50-quickprint-autologin.conf
  - /etc/xdg/openbox/autostart (QuickPrint screen-blanking snippet only if file matches)

Preserves:
  - Repository directory, .env, .env.display, data/, jobs/, logs/
  - CUPS packages, printers, and configuration
  - Installed apt packages (chromium, cups, etc.)
EOF
      exit 0
      ;;
    *)
      quickprint_die "Unknown argument: ${arg} (use --help)"
      ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  quickprint_die "Run as root: sudo ${SCRIPT_DIR}/uninstall_pi.sh"
fi

stop_disable_service() {
  local name=$1
  if systemctl is-active --quiet "$name" 2>/dev/null; then
    quickprint_log "Stopping ${name}"
    systemctl stop "$name"
  fi
  if systemctl is-enabled --quiet "$name" 2>/dev/null; then
    quickprint_log "Disabling ${name}"
    systemctl disable "$name"
  fi
}

quickprint_log "Removing QuickPrint systemd services"
stop_disable_service quickprint-agent.service
stop_disable_service quickprint-display.service

for unit in quickprint-agent.service quickprint-display.service; do
  if [[ -f "/etc/systemd/system/${unit}" ]]; then
    rm -f "/etc/systemd/system/${unit}"
    quickprint_log "Removed /etc/systemd/system/${unit}"
  fi
done

systemctl daemon-reload

if [[ "$PURGE_DISPLAY" -eq 1 ]]; then
  quickprint_log "Purging display autologin configuration"
  if [[ -f /etc/lightdm/lightdm.conf.d/50-quickprint-autologin.conf ]]; then
    rm -f /etc/lightdm/lightdm.conf.d/50-quickprint-autologin.conf
  fi
  if [[ -f /etc/xdg/openbox/autostart ]] && grep -q "unclutter -idle 0.5 -root" /etc/xdg/openbox/autostart 2>/dev/null; then
    rm -f /etc/xdg/openbox/autostart
    quickprint_log "Removed /etc/xdg/openbox/autostart"
  fi
fi

echo ""
echo "QuickPrint services removed."
echo "Repository, .env, .env.display, data/, jobs/, and logs were preserved."
echo "Remove the repository directory manually if no longer needed."
if [[ "$PURGE_DISPLAY" -eq 0 ]]; then
  echo "To also remove lightdm autologin config: sudo ${SCRIPT_DIR}/uninstall_pi.sh --purge-display"
fi
