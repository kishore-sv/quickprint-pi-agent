#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/quickprint-pi-agent}"
SERVICE_NAME="${SERVICE_NAME:-quickprint-agent}"

if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
  sudo systemctl disable --now "$SERVICE_NAME"
fi

if [[ -f /etc/systemd/system/quickprint-agent.service ]]; then
  sudo rm /etc/systemd/system/quickprint-agent.service
  sudo systemctl daemon-reload
fi

echo "Service removed. Data preserved at $INSTALL_DIR (including data/agent.db and .env)."
echo "Remove $INSTALL_DIR manually if you no longer need job history."
