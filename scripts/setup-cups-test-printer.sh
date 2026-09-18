#!/usr/bin/env bash
# Create a CUPS virtual/test printer queue for Agent development (no physical printer).
# On CUPS 2.x, file:// backends require FileDevice Yes in cups-files.conf.
set -euo pipefail

QUEUE_NAME="${CUPS_TEST_QUEUE:-quickprint-test}"
SPOOL_DIR="${CUPS_TEST_SPOOL:-/var/spool/quickprint-test}"
CUPS_FILES_CONF="${CUPS_FILES_CONF:-/etc/cups/cups-files.conf}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

if ! command -v lpadmin >/dev/null 2>&1; then
  echo "CUPS client tools not found. Install with:" >&2
  echo "  sudo apt install cups cups-client" >&2
  exit 1
fi

enable_file_device() {
  if [[ ! -f "$CUPS_FILES_CONF" ]]; then
    echo "CUPS config not found: ${CUPS_FILES_CONF}" >&2
    exit 1
  fi
  if grep -qE '^[[:space:]]*FileDevice[[:space:]]+Yes' "$CUPS_FILES_CONF"; then
    echo "FileDevice already enabled in ${CUPS_FILES_CONF}"
    return 0
  fi

  echo "Enabling FileDevice in ${CUPS_FILES_CONF} (required for file test queues on CUPS 2.x)"
  cp -a "${CUPS_FILES_CONF}" "${CUPS_FILES_CONF}.bak.$(date +%Y%m%d%H%M%S)"

  if grep -qE '^[[:space:]]*#?[[:space:]]*FileDevice' "$CUPS_FILES_CONF"; then
    sed -i -E 's/^[[:space:]]*#?[[:space:]]*FileDevice.*/FileDevice Yes/' "$CUPS_FILES_CONF"
  else
    printf '\n# QuickPrint test printer (file backend)\nFileDevice Yes\n' >> "$CUPS_FILES_CONF"
  fi

  echo "Restarting CUPS to apply FileDevice Yes"
  systemctl restart cups
  sleep 2
  if ! systemctl is-active --quiet cups; then
    echo "CUPS failed to restart after enabling FileDevice. Check journalctl -u cups" >&2
    exit 1
  fi
  if ! lpstat -r 2>/dev/null | grep -qi 'scheduler is running'; then
    echo "CUPS scheduler not running after restart. Check: lpstat -r" >&2
    exit 1
  fi
}

verify_queue() {
  if lpstat -p "${QUEUE_NAME}" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

echo "Creating CUPS test queue: ${QUEUE_NAME}"
echo "Output spool directory: ${SPOOL_DIR}"

mkdir -p "${SPOOL_DIR}"
chown root:lp "${SPOOL_DIR}" || true
chmod 775 "${SPOOL_DIR}" || true

if verify_queue; then
  echo "Queue ${QUEUE_NAME} already exists."
else
  enable_file_device
  echo "Adding queue via lpadmin..."
  if ! lpadmin -p "${QUEUE_NAME}" -E -v "file:${SPOOL_DIR}/" -m raw 2>&1; then
    echo "" >&2
    echo "lpadmin failed. Common causes:" >&2
    echo "  - FileDevice still disabled (check ${CUPS_FILES_CONF})" >&2
    echo "  - CUPS error log: sudo tail -30 /var/log/cups/error_log" >&2
    exit 1
  fi
fi

if ! verify_queue; then
  echo "Queue ${QUEUE_NAME} was not created." >&2
  echo "Check: sudo tail -30 /var/log/cups/error_log" >&2
  exit 1
fi

cupsenable "${QUEUE_NAME}" 2>/dev/null || true
cupsaccept "${QUEUE_NAME}" 2>/dev/null || true

echo ""
echo "Test queue ready."
lpstat -p "${QUEUE_NAME}" || true
echo ""
echo "Verify:"
echo "  lpstat -p ${QUEUE_NAME}"
echo "  lpstat -r"
echo ""
echo "Agent .env:"
echo "  PRINTER_MODE=cups"
echo "  CUPS_PRINTER_NAME=${QUEUE_NAME}"
echo "  CUPS_SERVER=          # leave empty for local Unix socket on Pi"
echo ""
echo "Then restart the agent:"
echo "  sudo systemctl restart quickprint-agent"
