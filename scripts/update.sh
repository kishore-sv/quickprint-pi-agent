#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${INSTALL_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
SERVICE_USER="${SERVICE_USER:-quickprint}"
SERVICE_NAME="${SERVICE_NAME:-quickprint-agent}"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This update script is intended for Linux." >&2
  exit 1
fi

if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
  sudo systemctl stop "$SERVICE_NAME"
  STOPPED=1
else
  STOPPED=0
fi

cd "$INSTALL_DIR"
if [[ -d .git ]]; then
  sudo -u "$SERVICE_USER" git pull --ff-only
fi

sudo -u "$SERVICE_USER" "$INSTALL_DIR/.venv/bin/pip" install -r requirements.txt

if [[ "$STOPPED" -eq 1 ]]; then
  sudo systemctl start "$SERVICE_NAME"
fi

sudo systemctl status "$SERVICE_NAME" --no-pager || true
