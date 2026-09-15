#!/usr/bin/env bash
# Create a CUPS virtual/test printer queue for Agent development (no physical printer).
set -euo pipefail

QUEUE_NAME="${CUPS_TEST_QUEUE:-quickprint-test}"
SPOOL_DIR="${CUPS_TEST_SPOOL:-/var/spool/quickprint-test}"

echo "Creating CUPS test queue: ${QUEUE_NAME}"
echo "Output spool directory: ${SPOOL_DIR}"

if ! command -v lpadmin >/dev/null 2>&1; then
  echo "CUPS client tools not found. Install with:" >&2
  echo "  sudo apt install cups cups-client" >&2
  exit 1
fi

sudo mkdir -p "${SPOOL_DIR}"
sudo chown root:lp "${SPOOL_DIR}" || true
sudo chmod 775 "${SPOOL_DIR}" || true

if lpstat -p "${QUEUE_NAME}" >/dev/null 2>&1; then
  echo "Queue ${QUEUE_NAME} already exists; enabling and accepting jobs."
else
  sudo lpadmin -p "${QUEUE_NAME}" -E -v "file:${SPOOL_DIR}/" -m raw
fi

sudo cupsenable "${QUEUE_NAME}"
sudo cupsaccept "${QUEUE_NAME}"

echo ""
echo "Test queue ready."
echo "Verify:"
echo "  lpstat -p ${QUEUE_NAME}"
echo "  lpstat -r"
echo ""
echo "Agent .env:"
echo "  PRINTER_MODE=cups"
echo "  CUPS_PRINTER_NAME=${QUEUE_NAME}"
echo "  CUPS_SERVER=localhost"
