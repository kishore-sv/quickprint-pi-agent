#!/usr/bin/env bash
# Start the print agent when configuration is valid; avoid systemd restart loops otherwise.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if ! "${SCRIPT_DIR}/check-agent-config.sh"; then
  echo "quickprint-agent: configuration incomplete — service idle until .env is fixed" >&2
  echo "  Fix ${REPO_DIR}/.env then: sudo systemctl restart quickprint-agent" >&2
  exec sleep infinity
fi

exec "${REPO_DIR}/.venv/bin/python" -m app.main
