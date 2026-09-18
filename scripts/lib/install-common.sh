#!/usr/bin/env bash
# Shared helpers for QuickPrint Pi installation scripts.
set -euo pipefail

quickprint_log() {
  echo "==> $*"
}

quickprint_warn() {
  echo "WARNING: $*" >&2
}

quickprint_die() {
  echo "ERROR: $*" >&2
  exit 1
}

quickprint_render_unit() {
  local template=$1
  local dest=$2
  local repo_dir=${REPO_DIR:?REPO_DIR required}
  local service_user=${SERVICE_USER:?SERVICE_USER required}
  local service_user_home=${SERVICE_USER_HOME:-"/home/${service_user}"}

  sed \
    -e "s|@REPO_DIR@|${repo_dir}|g" \
    -e "s|@SERVICE_USER@|${service_user}|g" \
    -e "s|@SERVICE_USER_HOME@|${service_user_home}|g" \
    "$template" > "$dest"
}

quickprint_apt_install_if_missing() {
  local pkg
  local missing=()
  for pkg in "$@"; do
    if ! dpkg -s "$pkg" >/dev/null 2>&1; then
      missing+=("$pkg")
    fi
  done
  if ((${#missing[@]} == 0)); then
    return 0
  fi
  quickprint_log "Installing apt packages: ${missing[*]}"
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing[@]}"
}

quickprint_user_in_group() {
  local user=$1
  local group=$2
  id -nG "$user" 2>/dev/null | tr ' ' '\n' | grep -qx "$group"
}

quickprint_is_placeholder() {
  local value=${1:-}
  [[ -z "$value" ]] && return 0
  [[ "$value" == REPLACE_* ]] && return 0
  return 1
}

quickprint_read_env_value() {
  local file=$1
  local key=$2
  local line
  if [[ ! -f "$file" ]]; then
    return 1
  fi
  line=$(grep -E "^${key}=" "$file" | tail -n 1 || true)
  [[ -n "$line" ]] || return 1
  echo "${line#*=}" | sed 's/^["'\''"]//;s/["'\''"]$//'
}
