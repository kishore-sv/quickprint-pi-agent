#!/usr/bin/env bash
# Legacy wrapper — use scripts/setup_pi.sh for new installations.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "scripts/install.sh is deprecated. Running scripts/setup_pi.sh ..."
exec bash "${SCRIPT_DIR}/setup_pi.sh" "$@"
