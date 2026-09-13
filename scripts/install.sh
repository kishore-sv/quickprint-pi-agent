#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/quickprint-pi-agent}"
SERVICE_USER="${SERVICE_USER:-quickprint}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This install script is intended for Linux (Raspberry Pi OS)." >&2
  exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python not found: $PYTHON_BIN" >&2
  exit 1
fi

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MINOR="${PY_VERSION#*.}"
if [[ "${PY_VERSION%%.*}" -lt 3 ]] || [[ "$PY_MINOR" -lt 13 ]]; then
  echo "Python 3.13+ required, found $PY_VERSION" >&2
  exit 1
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  sudo useradd --system --create-home --home-dir "/home/$SERVICE_USER" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

sudo mkdir -p "$INSTALL_DIR"
sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
  sudo -u "$SERVICE_USER" "$PYTHON_BIN" -m venv "$INSTALL_DIR/.venv"
fi

sudo -u "$SERVICE_USER" "$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

sudo -u "$SERVICE_USER" mkdir -p \
  "$INSTALL_DIR/data" \
  "$INSTALL_DIR/logs" \
  "$INSTALL_DIR/jobs/incoming" \
  "$INSTALL_DIR/jobs/processing" \
  "$INSTALL_DIR/jobs/completed" \
  "$INSTALL_DIR/jobs/failed"

if [[ ! -f "$INSTALL_DIR/.env" ]]; then
  sudo -u "$SERVICE_USER" cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
  echo "Created $INSTALL_DIR/.env — edit before production use."
else
  echo "Preserving existing $INSTALL_DIR/.env"
fi

sudo cp "$INSTALL_DIR/systemd/quickprint-agent.service" /etc/systemd/system/quickprint-agent.service
sudo systemctl daemon-reload

echo "Install complete."
echo "Next steps:"
echo "  1. Edit $INSTALL_DIR/.env (AGENT_ID, AGENT_SECRET, BACKEND_WS_URL, PRINTER_MODE)"
echo "  2. sudo systemctl enable --now quickprint-agent"
echo "  3. sudo journalctl -u quickprint-agent -f"
