#!/usr/bin/env bash
set -euo pipefail

: "${DISPLAY_URL:?DISPLAY_URL must be set in .env.display}"
: "${DISPLAY_TOKEN:?DISPLAY_TOKEN must be set in .env.display}"
: "${API_URL:?API_URL must be set in .env.display}"

export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-/home/quickprint/.Xauthority}"

INSTALL_ROOT="${INSTALL_ROOT:-/opt/quickprint-pi-agent}"
PROFILE_DIR="${INSTALL_ROOT}/var/chromium-kiosk"
BOOTSTRAP_URL="http://127.0.0.1:18765/"
SERVER_SCRIPT="${INSTALL_ROOT}/scripts/kiosk-display-server.py"

mkdir -p "$PROFILE_DIR"
chmod 700 "$PROFILE_DIR"

if [[ ! -f "$SERVER_SCRIPT" ]]; then
  echo "Bootstrap server not found: ${SERVER_SCRIPT}" >&2
  exit 1
fi

API_URL="${API_URL}" \
DISPLAY_URL="${DISPLAY_URL}" \
DISPLAY_TOKEN="${DISPLAY_TOKEN}" \
KIOSK_CODE="${KIOSK_CODE:-KIOSK-001}" \
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

CHROMIUM=""
for candidate in chromium chromium-browser google-chrome; do
  if command -v "$candidate" >/dev/null 2>&1; then
    CHROMIUM="$candidate"
    break
  fi
done

if [[ -z "$CHROMIUM" ]]; then
  echo "Chromium not found. Run scripts/setup-kiosk-display.sh" >&2
  exit 1
fi

exec "$CHROMIUM" \
  --user-data-dir="${PROFILE_DIR}" \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-translate \
  --check-for-update-interval=31536000 \
  --autoplay-policy=no-user-gesture-required \
  --disable-features=TranslateUI \
  --no-first-run \
  "${BOOTSTRAP_URL}"
