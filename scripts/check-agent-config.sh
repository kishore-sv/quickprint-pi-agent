#!/usr/bin/env bash
# Validate agent .env before starting (mirrors app/config.py production rules).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_DIR}/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing ${ENV_FILE}" >&2
  exit 1
fi

# shellcheck source=lib/install-common.sh
source "${SCRIPT_DIR}/lib/install-common.sh"

read_env() {
  quickprint_read_env_value "$ENV_FILE" "$1" 2>/dev/null || true
}

agent_env="$(read_env AGENT_ENV)"
[[ -z "$agent_env" ]] && agent_env="$(read_env ENVIRONMENT)"
[[ -z "$agent_env" ]] && agent_env="development"

printer_mode="$(read_env PRINTER_MODE)"
[[ -z "$printer_mode" ]] && printer_mode="mock"

if [[ "${printer_mode,,}" == "cups" ]]; then
  cups_name="$(read_env CUPS_PRINTER_NAME)"
  [[ -z "$cups_name" ]] && cups_name="$(read_env PRINTER_NAME)"
  [[ -z "$cups_name" ]] && cups_name="$(read_env CUPS_PRINTER)"
  if [[ -z "$cups_name" ]]; then
    echo "CUPS_PRINTER_NAME is required when PRINTER_MODE=cups" >&2
    echo "  Add a CUPS queue (sudo ${REPO_DIR}/scripts/setup-cups-test-printer.sh)" >&2
    echo "  Then set CUPS_PRINTER_NAME in ${ENV_FILE}" >&2
    exit 1
  fi
fi

if [[ "${agent_env,,}" == "development" ]]; then
  exit 0
fi

missing=()
agent_id="$(read_env AGENT_ID)"
agent_secret="$(read_env AGENT_SECRET)"
[[ -z "$agent_secret" ]] && agent_secret="$(read_env AGENT_TOKEN)"
backend_ws="$(read_env BACKEND_WS_URL)"

quickprint_is_placeholder "$agent_id" && missing+=("AGENT_ID")
quickprint_is_placeholder "$agent_secret" && missing+=("AGENT_SECRET")
[[ -z "$backend_ws" ]] && missing+=("BACKEND_WS_URL")

if ((${#missing[@]} > 0)); then
  echo "Production configuration missing: ${missing[*]}" >&2
  echo "  Edit ${ENV_FILE} (values from backend kiosk seed)" >&2
  exit 1
fi

exit 0
