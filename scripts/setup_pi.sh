#!/usr/bin/env bash
# QuickPrint Pi Agent — one-command first-time setup for Raspberry Pi OS.
# Idempotent. Does not modify application Python code.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=lib/install-common.sh
source "${SCRIPT_DIR}/lib/install-common.sh"

SERVICE_USER="${SERVICE_USER:-quickprint}"
SERVICE_USER_HOME="${SERVICE_USER_HOME:-/home/${SERVICE_USER}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Production sample defaults (override at install time)
AGENT_ENV="${AGENT_ENV:-production}"
AGENT_ID="${AGENT_ID:-}"
AGENT_SECRET="${AGENT_SECRET:-}"
BACKEND_URL="${BACKEND_URL:-https://qpapi.mmkerp.shop}"
BACKEND_WS_URL="${BACKEND_WS_URL:-wss://qpapi.mmkerp.shop/ws/kiosk}"
PRINTER_MODE="${PRINTER_MODE:-cups}"
CUPS_PRINTER_NAME="${CUPS_PRINTER_NAME:-}"
KIOSK_CODE="${KIOSK_CODE:-QP-KIOSK-001}"
KIOSK_DISPLAY_NAME="${KIOSK_DISPLAY_NAME:-QuickPrint Kiosk 1}"
API_URL="${API_URL:-https://qpapi.mmkerp.shop}"
DISPLAY_URL="${DISPLAY_URL:-https://qp.mmkerp.shop/kiosk/${KIOSK_CODE}}"
DISPLAY_TOKEN="${DISPLAY_TOKEN:-REPLACE_WITH_DISPLAY_TOKEN}"

ACTION_REQUIRED=()
VALIDATION_OK=()
VALIDATION_FAIL=()

record_ok() { VALIDATION_OK+=("$1"); }
record_fail() { VALIDATION_FAIL+=("$1"); }
record_action() { ACTION_REQUIRED+=("$1"); }

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    quickprint_die "Run as root: sudo ${SCRIPT_DIR}/setup_pi.sh"
  fi
}

detect_platform() {
  if [[ "$(uname -s)" != "Linux" ]]; then
    quickprint_die "This installer is for Linux (Raspberry Pi OS)."
  fi
  if [[ -f /proc/device-tree/model ]]; then
    local model
    model="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"
    if [[ -n "$model" ]] && [[ "$model" != *"Raspberry Pi"* ]]; then
      quickprint_warn "Not a Raspberry Pi (${model}). Continuing anyway."
    fi
  else
    quickprint_warn "Could not detect Raspberry Pi model. Continuing anyway."
  fi
}

check_python() {
  command -v "$PYTHON_BIN" >/dev/null 2>&1 || quickprint_die "Python not found: ${PYTHON_BIN}"
  local version minor major
  version="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  major="${version%%.*}"
  minor="${version#*.}"
  if [[ "$major" -lt 3 ]] || [[ "$minor" -lt 13 ]]; then
    quickprint_die "Python 3.13+ required, found ${version}. Upgrade Raspberry Pi OS or install Python 3.13."
  fi
  record_ok "Python ${version}"
}

install_base_packages() {
  quickprint_log "Checking base apt dependencies"
  quickprint_apt_install_if_missing \
    git \
    curl \
    ca-certificates \
    python3 \
    python3-venv \
    python3-pip \
    cups \
    cups-client \
    avahi-daemon
}

setup_cups() {
  quickprint_log "Enabling CUPS"
  systemctl enable cups >/dev/null 2>&1 || true
  systemctl start cups
  if ! systemctl is-active --quiet cups; then
    quickprint_die "CUPS service is not running. Check: journalctl -u cups -n 50"
  fi
  if ! lpstat -r 2>/dev/null | grep -qi "scheduler is running"; then
    quickprint_die "CUPS scheduler is not running. Check: lpstat -r"
  fi
  record_ok "CUPS running"
}

ensure_service_user() {
  if id "$SERVICE_USER" &>/dev/null; then
    quickprint_log "Using existing user: ${SERVICE_USER}"
    if [[ "$SERVICE_USER_HOME" != "$(eval echo "~${SERVICE_USER}")" ]]; then
      SERVICE_USER_HOME="$(eval echo "~${SERVICE_USER}")"
    fi
    return 0
  fi

  quickprint_log "Creating user ${SERVICE_USER}"
  useradd -m -s /bin/bash "$SERVICE_USER"
  SERVICE_USER_HOME="$(eval echo "~${SERVICE_USER}")"
}

fix_ownership() {
  quickprint_log "Setting ownership on ${REPO_DIR}"
  chown -R "${SERVICE_USER}:${SERVICE_USER}" "$REPO_DIR"
}

setup_venv() {
  quickprint_log "Python virtual environment"
  if [[ ! -d "${REPO_DIR}/.venv" ]]; then
    sudo -u "$SERVICE_USER" "$PYTHON_BIN" -m venv "${REPO_DIR}/.venv"
  fi
  sudo -u "$SERVICE_USER" "${REPO_DIR}/.venv/bin/pip" install --upgrade pip
  sudo -u "$SERVICE_USER" "${REPO_DIR}/.venv/bin/pip" install -r "${REPO_DIR}/requirements.txt"
  record_ok "Virtual environment ${REPO_DIR}/.venv"
}

setup_directories() {
  quickprint_log "Creating runtime directories"
  sudo -u "$SERVICE_USER" mkdir -p \
    "${REPO_DIR}/data" \
    "${REPO_DIR}/logs" \
    "${REPO_DIR}/jobs/incoming" \
    "${REPO_DIR}/jobs/processing" \
    "${REPO_DIR}/jobs/completed" \
    "${REPO_DIR}/jobs/failed" \
    "${REPO_DIR}/var/chromium-kiosk"
  record_ok "Runtime directories"
}

write_agent_env() {
  local env_file="${REPO_DIR}/.env"
  if [[ -f "$env_file" ]]; then
    quickprint_log "Preserving existing ${env_file}"
    record_ok "Environment file ${env_file} (existing)"
    return 0
  fi

  quickprint_log "Creating ${env_file} from template"
  cat >"$env_file" <<EOF
AGENT_ENV=${AGENT_ENV}
AGENT_ID=${AGENT_ID:-REPLACE_WITH_AGENT_ID}
AGENT_SECRET=${AGENT_SECRET:-REPLACE_WITH_AGENT_SECRET}
BACKEND_URL=${BACKEND_URL}
BACKEND_WS_URL=${BACKEND_WS_URL}
JOB_DIRECTORY=jobs
DATABASE_PATH=data/agent.db
PRINTER_MODE=${PRINTER_MODE}
CUPS_PRINTER_NAME=${CUPS_PRINTER_NAME}
CUPS_SERVER=
LOG_LEVEL=INFO
MAX_DOWNLOAD_BYTES=52428800
MOCK_PRINT_DELAY_SECONDS=0.1
MOCK_PRINT_FAILURE=false
DOWNLOAD_TIMEOUT_SECONDS=120
HEARTBEAT_INTERVAL_SECONDS=30
HEALTH_REFRESH_INTERVAL_SECONDS=60
WS_RECONNECT_MAX_DELAY_SECONDS=60
RETRY_MAX_ATTEMPTS=3
RETRY_BASE_DELAY_SECONDS=1.0
RETRY_MAX_DELAY_SECONDS=30.0
CUPS_COMMAND_TIMEOUT_SECONDS=30
JOB_POLL_INTERVAL_SECONDS=1.0
EOF
  chown "${SERVICE_USER}:${SERVICE_USER}" "$env_file"
  chmod 600 "$env_file"
  record_ok "Environment file ${env_file} (created)"
}

write_display_env() {
  local env_file="${REPO_DIR}/.env.display"
  if [[ -f "$env_file" ]]; then
    quickprint_log "Preserving existing ${env_file}"
    record_ok "Display environment ${env_file} (existing)"
    return 0
  fi

  quickprint_log "Creating ${env_file}"
  cat >"$env_file" <<EOF
KIOSK_CODE=${KIOSK_CODE}
KIOSK_DISPLAY_NAME=${KIOSK_DISPLAY_NAME}
API_URL=${API_URL}
DISPLAY_URL=${DISPLAY_URL}
DISPLAY_TOKEN=${DISPLAY_TOKEN}
EOF
  chown "${SERVICE_USER}:${SERVICE_USER}" "$env_file"
  chmod 600 "$env_file"
  record_ok "Display environment ${env_file} (created)"
}

setup_cups_permissions() {
  if quickprint_user_in_group "$SERVICE_USER" lp; then
    quickprint_log "${SERVICE_USER} already in group lp"
  else
    quickprint_log "Adding ${SERVICE_USER} to group lp"
    usermod -aG lp "$SERVICE_USER"
  fi
}

install_systemd_units() {
  quickprint_log "Installing systemd units"
  quickprint_render_unit \
    "${REPO_DIR}/systemd/quickprint-agent.service" \
    /etc/systemd/system/quickprint-agent.service
  quickprint_render_unit \
    "${REPO_DIR}/systemd/quickprint-display.service" \
    /etc/systemd/system/quickprint-display.service
  systemctl daemon-reload
  systemctl enable quickprint-agent.service
  systemctl enable quickprint-display.service
  record_ok "Systemd units installed and enabled"
}

setup_display_stack() {
  quickprint_log "Configuring kiosk display stack"
  SKIP_DISPLAY_SYSTEMD=1 REPO_DIR="$REPO_DIR" INSTALL_ROOT="$REPO_DIR" \
    SERVICE_USER="$SERVICE_USER" SERVICE_USER_HOME="$SERVICE_USER_HOME" \
    bash "${SCRIPT_DIR}/setup-kiosk-display.sh"
}

agent_config_ready() {
  local env_file="${REPO_DIR}/.env"
  local id secret ws printer
  id="$(quickprint_read_env_value "$env_file" AGENT_ID || true)"
  secret="$(quickprint_read_env_value "$env_file" AGENT_SECRET || true)"
  ws="$(quickprint_read_env_value "$env_file" BACKEND_WS_URL || true)"
  printer="$(quickprint_read_env_value "$env_file" CUPS_PRINTER_NAME || true)"
  local mode
  mode="$(quickprint_read_env_value "$env_file" PRINTER_MODE || true)"

  if quickprint_is_placeholder "$id" || quickprint_is_placeholder "$secret" || [[ -z "$ws" ]]; then
    record_action "Set AGENT_ID, AGENT_SECRET, and BACKEND_WS_URL in ${REPO_DIR}/.env (from backend kiosk seed)"
    return 1
  fi
  if [[ "$mode" == "cups" ]] && [[ -z "$printer" ]]; then
    record_action "Set CUPS_PRINTER_NAME in ${REPO_DIR}/.env after adding a CUPS printer queue"
    return 1
  fi
  return 0
}

display_config_ready() {
  local env_file="${REPO_DIR}/.env.display"
  local token url
  token="$(quickprint_read_env_value "$env_file" DISPLAY_TOKEN || true)"
  url="$(quickprint_read_env_value "$env_file" DISPLAY_URL || true)"
  if quickprint_is_placeholder "$token" || [[ -z "$url" ]]; then
    record_action "Set DISPLAY_TOKEN and DISPLAY_URL in ${REPO_DIR}/.env.display (from backend kiosk seed)"
    return 1
  fi
  return 0
}

start_services() {
  quickprint_log "Starting services when configuration is ready"
  if agent_config_ready; then
    systemctl restart quickprint-agent.service || systemctl start quickprint-agent.service
    if systemctl is-active --quiet quickprint-agent.service; then
      record_ok "quickprint-agent running"
    else
      record_fail "quickprint-agent not running (check journalctl -u quickprint-agent -n 50)"
    fi
  else
    systemctl stop quickprint-agent.service 2>/dev/null || true
    record_action "quickprint-agent left stopped until ${REPO_DIR}/.env is configured"
  fi

  if display_config_ready; then
    systemctl restart quickprint-display.service || systemctl start quickprint-display.service
    if systemctl is-active --quiet quickprint-display.service; then
      record_ok "quickprint-display running"
    else
      record_fail "quickprint-display not running (check journalctl -u quickprint-display -n 50)"
    fi
  else
    systemctl stop quickprint-display.service 2>/dev/null || true
    record_action "quickprint-display left stopped until ${REPO_DIR}/.env.display is configured"
  fi
}

check_backend_connectivity() {
  local env_file="${REPO_DIR}/.env"
  local url
  url="$(quickprint_read_env_value "$env_file" BACKEND_URL || true)"
  if [[ -z "$url" ]]; then
    url="$BACKEND_URL"
  fi
  local health_url="${url%/}/health"
  quickprint_log "Checking backend connectivity: ${health_url}"
  if curl -fsS --max-time 10 "$health_url" >/dev/null 2>&1; then
    record_ok "Backend reachable (${health_url})"
  else
    record_action "Backend not reachable at ${health_url} — verify network and BACKEND_URL"
  fi
}

validate_installation() {
  [[ -d "${REPO_DIR}/.venv" ]] || record_fail "Missing .venv"
  [[ -f "${REPO_DIR}/.env" ]] || record_fail "Missing .env"
  [[ -f "${REPO_DIR}/.env.display" ]] || record_fail "Missing .env.display"

  if sudo -u "$SERVICE_USER" "${REPO_DIR}/.venv/bin/python" -c "import websockets" 2>/dev/null; then
    record_ok "Python dependency websockets"
  else
    record_fail "websockets not importable in venv"
  fi

  if systemctl is-enabled --quiet quickprint-agent.service 2>/dev/null; then
    record_ok "quickprint-agent enabled"
  else
    record_fail "quickprint-agent not enabled"
  fi

  if systemctl is-enabled --quiet quickprint-display.service 2>/dev/null; then
    record_ok "quickprint-display enabled"
  else
    record_fail "quickprint-display not enabled"
  fi
}

print_summary() {
  local kiosk
  kiosk="$(quickprint_read_env_value "${REPO_DIR}/.env.display" KIOSK_CODE 2>/dev/null || echo "$KIOSK_CODE")"
  local backend
  backend="$(quickprint_read_env_value "${REPO_DIR}/.env" BACKEND_URL 2>/dev/null || echo "$BACKEND_URL")"

  echo ""
  echo "=========================================="
  echo "   QuickPrint Pi Setup Complete"
  echo "=========================================="
  echo ""
  echo "Repository:"
  echo "  ${REPO_DIR}"
  echo ""
  echo "Python:"
  echo "  $("$PYTHON_BIN" --version 2>&1 | awk '{print $2}')"
  echo ""
  echo "Virtual environment:"
  echo "  ${REPO_DIR}/.venv"
  echo ""
  echo "Environment:"
  echo "  ${REPO_DIR}/.env"
  echo "  ${REPO_DIR}/.env.display"
  echo ""
  echo "CUPS:"
  if systemctl is-active --quiet cups; then
    echo "  Running"
  else
    echo "  NOT running"
  fi
  echo ""
  echo "Pi Agent:"
  if systemctl is-enabled --quiet quickprint-agent 2>/dev/null; then
    echo "  Enabled"
  else
    echo "  Not enabled"
  fi
  if systemctl is-active --quiet quickprint-agent 2>/dev/null; then
    echo "  Running"
  else
    echo "  Not running"
  fi
  echo ""
  echo "Display:"
  if systemctl is-enabled --quiet quickprint-display 2>/dev/null; then
    echo "  Configured (enabled)"
  else
    echo "  Not configured"
  fi
  if systemctl is-active --quiet quickprint-display 2>/dev/null; then
    echo "  Running"
  else
    echo "  Not running"
  fi
  echo ""
  echo "API:"
  echo "  ${backend}"
  echo ""
  echo "Kiosk:"
  echo "  ${kiosk}"
  echo ""

  if ((${#VALIDATION_OK[@]} > 0)); then
    echo "Checks passed:"
    for item in "${VALIDATION_OK[@]}"; do
      echo "  [ok] ${item}"
    done
    echo ""
  fi

  if ((${#VALIDATION_FAIL[@]} > 0)); then
    echo "Checks failed:"
    for item in "${VALIDATION_FAIL[@]}"; do
      echo "  [!!] ${item}"
    done
    echo ""
  fi

  if ((${#ACTION_REQUIRED[@]} > 0)); then
    echo "ACTION REQUIRED:"
    for item in "${ACTION_REQUIRED[@]}"; do
      echo "  - ${item}"
    done
    echo ""
  fi

  echo "Useful commands:"
  echo "  sudo systemctl status quickprint-agent"
  echo "  sudo journalctl -u quickprint-agent -f"
  echo "  sudo systemctl status quickprint-display"
  echo "  sudo journalctl -u quickprint-display -f"
  echo "  lpstat -r"
  echo "  lpstat -p -d"
  echo "  sudo systemctl restart quickprint-agent"
  echo "  sudo systemctl restart quickprint-display"
  echo ""
  echo "Reboot to verify boot-time autostart:"
  echo "  sudo reboot"
  echo "=========================================="
}

main() {
  require_root
  detect_platform
  quickprint_log "QuickPrint Pi setup"
  quickprint_log "Repository: ${REPO_DIR}"

  check_python
  install_base_packages
  setup_cups
  ensure_service_user
  fix_ownership
  setup_venv
  setup_directories
  write_agent_env
  write_display_env
  setup_cups_permissions
  install_systemd_units
  setup_display_stack
  start_services
  check_backend_connectivity
  validate_installation
  print_summary
}

main "$@"
