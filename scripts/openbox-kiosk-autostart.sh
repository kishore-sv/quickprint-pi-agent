#!/usr/bin/env bash
# Launched from openbox autostart inside the logged-in X session (preferred kiosk path).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${REPO_DIR}/.env.display"

if [[ ! -f "$ENV_FILE" ]]; then
  exit 0
fi

# shellcheck source=lib/install-common.sh
source "${REPO_DIR}/scripts/lib/install-common.sh"

token="$(quickprint_read_env_value "$ENV_FILE" DISPLAY_TOKEN || true)"
if quickprint_is_placeholder "$token"; then
  echo "openbox-kiosk-autostart: DISPLAY_TOKEN not set in ${ENV_FILE}" >&2
  exit 0
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

export INSTALL_ROOT="$REPO_DIR"
export SERVICE_USER_HOME="${HOME}"
export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-${HOME}/.Xauthority}"

exec "${REPO_DIR}/scripts/run-kiosk-display.sh"
