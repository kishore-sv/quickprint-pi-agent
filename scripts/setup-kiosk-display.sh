#!/usr/bin/env bash
# QuickPrint kiosk display setup for Raspberry Pi OS / Debian with HDMI monitor.
# Installs minimal graphical stack + Chromium and configures quickprint-display.service.
set -euo pipefail

INSTALL_ROOT="${INSTALL_ROOT:-/opt/quickprint-pi-agent}"
SERVICE_USER="${SERVICE_USER:-quickprint}"
DISPLAY_ENV_FILE="${INSTALL_ROOT}/.env.display"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

echo "==> Installing graphical packages"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  xserver-xorg \
  x11-xserver-utils \
  openbox \
  chromium \
  unclutter \
  lightdm

if ! id "$SERVICE_USER" &>/dev/null; then
  echo "User $SERVICE_USER not found. Run scripts/install.sh first." >&2
  exit 1
fi

echo "==> Configuring autologin for $SERVICE_USER (lightdm)"
mkdir -p /etc/lightdm/lightdm.conf.d
cat > /etc/lightdm/lightdm.conf.d/50-quickprint-autologin.conf <<EOF
[Seat:*]
autologin-user=${SERVICE_USER}
autologin-user-timeout=0
user-session=openbox
EOF

echo "==> Disabling screen blanking"
mkdir -p /etc/xdg/openbox
cat > /etc/xdg/openbox/autostart <<'EOF'
xset s off
xset -dpms
xset s noblank
unclutter -idle 0.5 -root &
EOF

if [[ ! -f "$DISPLAY_ENV_FILE" ]]; then
  cat > "$DISPLAY_ENV_FILE" <<EOF
# QuickPrint kiosk display configuration (read-only token; NOT the agent secret)
KIOSK_CODE=KIOSK-001
KIOSK_DISPLAY_NAME=Development Kiosk
API_URL=https://quickprint.fun
DISPLAY_URL=https://quickprint.fun/kiosk/KIOSK-001
DISPLAY_TOKEN=
EOF
  chown "${SERVICE_USER}:${SERVICE_USER}" "$DISPLAY_ENV_FILE"
  chmod 600 "$DISPLAY_ENV_FILE"
  echo "Created ${DISPLAY_ENV_FILE} — set DISPLAY_TOKEN and DISPLAY_URL from: bun run kiosk:seed --rotate-display-token"
fi

chmod +x "${INSTALL_ROOT}/scripts/run-kiosk-display.sh" \
  "${INSTALL_ROOT}/scripts/kiosk-display-boot.sh" \
  "${INSTALL_ROOT}/scripts/kiosk-display-server.py"

echo "==> Installing systemd unit"
cp "${INSTALL_ROOT}/systemd/quickprint-display.service" /etc/systemd/system/quickprint-display.service
systemctl daemon-reload
systemctl enable quickprint-display.service

echo ""
echo "Setup complete."
echo "1. Set API_URL, DISPLAY_URL, and DISPLAY_TOKEN in ${DISPLAY_ENV_FILE}"
echo "2. sudo systemctl start quickprint-display.service"
echo "3. sudo systemctl status quickprint-display.service"
