#!/usr/bin/env bash
set -euo pipefail

DEFAULT_INSTALL_DIR="${INSTALL_DIR:-$HOME/chat2api}"
DEFAULT_PORT="60403"
DEFAULT_API_PREFIX="nanapi-2026-a1"

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
elif command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
else
  echo "需要 root 权限或安装 sudo"
  exit 1
fi

prompt() {
  local var_name="$1"
  local prompt_text="$2"
  local default_value="${3:-}"
  local current_value=""
  read -r -p "$prompt_text [$default_value]: " current_value
  if [[ -z "$current_value" ]]; then
    current_value="$default_value"
  fi
  printf -v "$var_name" '%s' "$current_value"
}

shell_escape() {
  printf "%s" "$1" | sed "s/'/'\\\\''/g"
}

echo "== Install chat2api manage command =="
prompt INSTALL_DIR "Compose directory" "$DEFAULT_INSTALL_DIR"
prompt PORT "Host port" "$DEFAULT_PORT"
prompt API_PREFIX "API prefix" "$DEFAULT_API_PREFIX"

if [[ ! -f "$INSTALL_DIR/docker-compose.yml" && ! -f "$INSTALL_DIR/compose.yml" && ! -f "$INSTALL_DIR/compose.yaml" ]]; then
  echo "No docker compose file found in: $INSTALL_DIR"
  exit 1
fi

SCRIPT_SOURCE="${BASH_SOURCE[0]-}"
SCRIPT_SOURCE_DIR=""
if [ -n "$SCRIPT_SOURCE" ] && [ -f "$SCRIPT_SOURCE" ]; then
  SCRIPT_SOURCE_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"
fi
$SUDO mkdir -p /etc
$SUDO tee /etc/chat2api.env >/dev/null <<EOF
INSTALL_DIR='$(shell_escape "$INSTALL_DIR")'
PORT='$(shell_escape "$PORT")'
API_PREFIX='$(shell_escape "$API_PREFIX")'
EOF

if [ -n "$SCRIPT_SOURCE_DIR" ] && [ -f "$SCRIPT_SOURCE_DIR/chat2api.sh" ]; then
  $SUDO install -m 0755 "$SCRIPT_SOURCE_DIR/chat2api.sh" /usr/local/bin/chat2api
else
  tmp_script="$(mktemp)"
  curl -fsSL "https://raw.githubusercontent.com/nanashiwang/chat2api/main/deploy/chat2api.sh" -o "$tmp_script"
  $SUDO install -m 0755 "$tmp_script" /usr/local/bin/chat2api
  rm -f "$tmp_script"
fi

echo
echo "Installed."
echo "Try: chat2api status"
echo "Then: chat2api update"
