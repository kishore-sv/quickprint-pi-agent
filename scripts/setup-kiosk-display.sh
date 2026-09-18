#!/usr/bin/env bash
# QuickPrint kiosk display setup for Raspberry Pi OS / Debian with HDMI monitor.
# Installs minimal graphical stack + Chromium and configures quickprint-display.service.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/install-common.sh
source "${SCRIPT_DIR}/lib/install-common.sh"

REPO_DIR="${REPO_DIR:-${INSTALL_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}}"
INSTALL_ROOT="${INSTALL_ROOT:-$REPO_DIR}"
SERVICE_USER="${SERVICE_USER:-quickprint}"
SERVICE_USER_HOME="${SERVICE_USER_HOME:-/home/${SERVICE_USER}}"
DISPLAY_ENV_FILE="${INSTALL_ROOT}/.env.display"
DISPLAY_TEMPLATE="${REPO_DIR}/config/display.env.example"
SKIP_DISPLAY_SYSTEMD="${SKIP_DISPLAY_SYSTEMD:-0}"

if [[ "${EUID}" -ne 0 ]]; then
  quickprint_die "Run as root: sudo bash $0"
fi

quickprint_log "Installing graphical packages (if missing)"
quickprint_apt_install_if_missing \
  xserver-xorg \
  x11-xserver-utils \
  openbox \
  chromium \
  unclutter \
  lightdm

if ! id "$SERVICE_USER" &>/dev/null; then
  quickprint_die "User $SERVICE_USER not found. Run scripts/setup_pi.sh first."
fi

quickprint_log "Configuring autologin for $SERVICE_USER (lightdm)"
mkdir -p /etc/lightdm/lightdm.conf.d
cat > /etc/lightdm/lightdm.conf.d/50-quickprint-autologin.conf <<EOF
[Seat:*]
autologin-user=${SERVICE_USER}
autologin-user-timeout=0
user-session=openbox
EOF

quickprint_log "Disabling screen blanking (openbox autostart)"
mkdir -p /etc/xdg/openbox
cat > /etc/xdg/openbox/autostart <<'EOF'
xset s off
xset -dpms
xset s noblank
unclutter -idle 0.5 -root &
EOF

if [[ ! -f "$DISPLAY_ENV_FILE" ]]; then
  if [[ -f "$DISPLAY_TEMPLATE" ]]; then
    cp "$DISPLAY_TEMPLATE" "$DISPLAY_ENV_FILE"
  else
    cat > "$DISPLAY_ENV_FILE" <<EOF
KIOSK_CODE=QP-KIOSK-001
KIOSK_DISPLAY_NAME=QuickPrint Kiosk 1
API_URL=https://qpapi.mmkerp.shop
DISPLAY_URL=https://qp.mmkerp.shop/kiosk/QP-KIOSK-001
DISPLAY_TOKEN=REPLACE_WITH_DISPLAY_TOKEN
EOF
  fi
  chown "${SERVICE_USER}:${SERVICE_USER}" "$DISPLAY_ENV_FILE"
  chmod 600 "$DISPLAY_ENV_FILE"
  quickprint_log "Created ${DISPLAY_ENV_FILE} — set DISPLAY_TOKEN before starting display service"
else
  quickprint_log "Preserving existing ${DISPLAY_ENV_FILE}"
fi

chmod +x "${INSTALL_ROOT}/scripts/run-kiosk-display.sh" \
  "${INSTALL_ROOT}/scripts/kiosk-display-boot.sh" \
  "${INSTALL_ROOT}/scripts/kiosk-display-server.py"

if [[ "$SKIP_DISPLAY_SYSTEMD" != "1" ]]; then
  quickprint_log "Installing quickprint-display systemd unit"
  quickprint_render_unit \
    "${REPO_DIR}/systemd/quickprint-display.service" \
    /etc/systemd/system/quickprint-display.service
  systemctl daemon-reload
  systemctl enable quickprint-display.service
fi

quickprint_log "Kiosk display stack configured"
