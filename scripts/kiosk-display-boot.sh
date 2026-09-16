#!/usr/bin/env bash
# Start the local bootstrap server for Mac/dev testing.
# Usage:
#   API_URL=http://127.0.0.1:8000 \
#   DISPLAY_URL=http://<FRONTEND_LAN_IP>:3000/kiosk/KIOSK-001 \
#   DISPLAY_TOKEN=<token> \
#   KIOSK_CODE=KIOSK-001 \
#   ./scripts/kiosk-display-boot.sh
set -euo pipefail

: "${API_URL:?API_URL is required}"
: "${DISPLAY_URL:?DISPLAY_URL is required}"
: "${DISPLAY_TOKEN:?DISPLAY_TOKEN is required}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_SCRIPT="${SCRIPT_DIR}/kiosk-display-server.py"
BOOTSTRAP_URL="http://127.0.0.1:18765/"

export KIOSK_CODE="${KIOSK_CODE:-KIOSK-001}"

python3 "$SERVER_SCRIPT" &
SERVER_PID=$!

cleanup() {
  if kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 30); do
  if python3 -c "import socket; s=socket.create_connection(('127.0.0.1', 18765), 0.2); s.close()" 2>/dev/null; then
    break
  fi
  sleep 0.2
done

echo "Bootstrap server: ${BOOTSTRAP_URL}"
echo "Open in Chromium: ${BOOTSTRAP_URL}"

if [[ "$(uname -s)" == "Darwin" ]]; then
  open "${BOOTSTRAP_URL}"
fi

wait "$SERVER_PID"
