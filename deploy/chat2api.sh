#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="/etc/chat2api.env"
GITHUB_RAW_DEFAULT="https://raw.githubusercontent.com/nanashiwang/chat2api/main"
GITHUB_REPO_DEFAULT="https://github.com/nanashiwang/chat2api"

if [[ -f "$CONFIG_FILE" ]]; then
  # shellcheck disable=SC1091
  source "$CONFIG_FILE"
fi

GITHUB_RAW="${GITHUB_RAW:-$GITHUB_RAW_DEFAULT}"
GITHUB_REPO="${GITHUB_REPO:-$GITHUB_REPO_DEFAULT}"

detect_install_dir() {
  if [[ -n "${INSTALL_DIR:-}" && -d "${INSTALL_DIR:-}" ]]; then
    printf "%s\n" "$INSTALL_DIR"
    return
  fi

  if [[ -f "./docker-compose.yml" || -f "./compose.yml" || -f "./compose.yaml" ]]; then
    pwd
    return
  fi

  local candidates=(
    "/opt/chat2api"
    "/opt/chat2api/data"
    "/srv/chat2api"
    "/root/chat2api"
    "$HOME/chat2api"
  )

  local dir
  for dir in "${candidates[@]}"; do
    if [[ -f "$dir/docker-compose.yml" || -f "$dir/compose.yml" || -f "$dir/compose.yaml" || -x "$dir/deploy/multi/manage.sh" ]]; then
      printf "%s\n" "$dir"
      return
    fi
  done

  return 1
}

INSTALL_DIR="$(detect_install_dir || true)"
if [[ -z "$INSTALL_DIR" ]]; then
  echo "Cannot find chat2api compose directory."
  echo "Run this command inside your deployment directory,"
  echo "or create /etc/chat2api.env,"
  echo "or run deploy/install.sh / deploy/install-command.sh first."
  exit 1
fi

cd "$INSTALL_DIR"

is_multi_install() {
  [[ -x "$INSTALL_DIR/deploy/multi/manage.sh" ]]
}

is_multi_generated() {
  [[ -f "$INSTALL_DIR/deploy/multi/generated/docker-compose.yml" ]]
}

run_multi_manage() {
  (cd "$INSTALL_DIR/deploy/multi" && ./manage.sh "$@")
}

install_latest_cli_from_repo() {
  local src="$INSTALL_DIR/deploy/chat2api.sh"
  [[ -f "$src" ]] || return 0
  if [[ "$(id -u)" -eq 0 ]]; then
    install -m 0755 "$src" /usr/local/bin/chat2api 2>/dev/null && echo "[✓] 管理命令已更新: /usr/local/bin/chat2api" || true
  elif command -v sudo >/dev/null 2>&1; then
    sudo install -m 0755 "$src" /usr/local/bin/chat2api 2>/dev/null && echo "[✓] 管理命令已更新: /usr/local/bin/chat2api" || true
  fi
}

install_latest_cli_from_remote() {
  local tmp_script
  tmp_script="$(mktemp)" || return 0
  if curl -fsSL --max-time 15 "$GITHUB_RAW/deploy/chat2api.sh" -o "$tmp_script"; then
    if [[ "$(id -u)" -eq 0 ]]; then
      install -m 0755 "$tmp_script" /usr/local/bin/chat2api 2>/dev/null && echo "[✓] 管理命令已更新: /usr/local/bin/chat2api" || true
    elif command -v sudo >/dev/null 2>&1; then
      sudo install -m 0755 "$tmp_script" /usr/local/bin/chat2api 2>/dev/null && echo "[✓] 管理命令已更新: /usr/local/bin/chat2api" || true
    fi
  else
    echo "[!] 管理命令更新失败，继续执行当前操作"
  fi
  rm -f "$tmp_script"
}

sync_deploy_assets_from_remote() {
  if [[ "${NO_PULL:-0}" == "1" ]]; then
    return 0
  fi
  if ! command -v tar >/dev/null 2>&1; then
    echo "[!] tar 不可用，跳过部署脚本同步"
    return 0
  fi

  local tmp_dir archive_dir
  tmp_dir="$(mktemp -d)" || return 0
  echo "[*] 同步部署脚本与编排面板..."
  if curl -fsSL --max-time 30 "${GITHUB_REPO}/archive/refs/heads/main.tar.gz" | tar -xz -C "$tmp_dir"; then
    archive_dir="$(find "$tmp_dir" -maxdepth 1 -type d -name 'chat2api-*' | head -1)"
    if [[ -n "$archive_dir" && -d "$archive_dir/deploy" ]]; then
      mkdir -p "$INSTALL_DIR/deploy"
      cp -R "$archive_dir/deploy"/. "$INSTALL_DIR/deploy/"
      chmod +x "$INSTALL_DIR/deploy/chat2api.sh" "$INSTALL_DIR/deploy/multi/manage.sh" 2>/dev/null || true
      install_latest_cli_from_repo
      echo "[✓] 部署脚本与编排面板已同步"
    else
      echo "[!] 仓库包缺少 deploy/，跳过同步"
    fi
  else
    echo "[!] 部署脚本同步失败，继续使用当前版本"
  fi
  rm -rf "$tmp_dir"
}

update_repo_for_multi() {
  # 让 `chat2api update` 自己先更新部署脚本，再调用 deploy/multi/manage.sh。
  # 本地跟踪文件改动会自动放入 git stash；不 reset、不删除用户改动。
  if [[ "${NO_PULL:-0}" == "1" ]]; then
    echo "[*] NO_PULL=1，跳过 git pull"
    return 0
  fi

  local repo_root branch stash_msg=""
  if ! repo_root="$(git -C "$INSTALL_DIR" rev-parse --show-toplevel 2>/dev/null)"; then
    echo "[*] 非 git 仓库，改用 GitHub 包同步"
    sync_deploy_assets_from_remote
    return 0
  fi
  branch="$(git -C "$repo_root" rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)"
  if [[ "$branch" == "HEAD" ]]; then
    echo "[*] detached HEAD，跳过 git pull"
    return 0
  fi

  if [[ -n "$(git -C "$repo_root" status --porcelain 2>/dev/null)" ]]; then
    stash_msg="chat2api auto-stash before update $(date -u +%Y%m%dT%H%M%SZ)"
    echo "[*] 检测到本地改动，自动暂存到 git stash..."
    if git -C "$repo_root" stash push -m "$stash_msg" -- . >/dev/null 2>&1; then
      echo "[✓] 本地改动已暂存：$stash_msg"
    else
      echo "[!] 自动暂存失败，继续使用当前代码"
      return 0
    fi
  fi

  echo "[*] git pull --ff-only ($branch)..."
  if git -C "$repo_root" pull --ff-only --quiet; then
    echo "[✓] 代码已同步到 $(git -C "$repo_root" log -1 --pretty='%h %s')"
    install_latest_cli_from_repo
    if [[ -n "$stash_msg" ]]; then
      echo "[i] 被暂存的本地改动可用以下命令查看：git -C \"$repo_root\" stash list"
    fi
  else
    if [[ -n "$stash_msg" ]]; then
      git -C "$repo_root" stash pop --quiet >/dev/null 2>&1 || true
    fi
    echo "[!] git pull 失败，已继续使用当前代码"
  fi
}

as_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    echo "需要 root 权限或安装 sudo"
    return 1
  fi
}

run_compose() {
  if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    echo "docker compose is not available"
    exit 1
  fi

  if [[ "$(id -u)" -eq 0 ]] || docker info >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo docker compose "$@"
  else
    echo "docker requires root permission or sudo"
    exit 1
  fi
}

stop_single_compose_if_present() {
  if [[ -f "$INSTALL_DIR/docker-compose.yml" || -f "$INSTALL_DIR/compose.yml" || -f "$INSTALL_DIR/compose.yaml" ]]; then
    run_compose down --remove-orphans
    return
  fi
  return 1
}

remove_known_chat2api_containers() {
  if ! command -v docker >/dev/null 2>&1; then
    return 0
  fi
  docker rm -f chat2api watchtower c2a-nginx c2a-orchestrator c2a-watchtower >/dev/null 2>&1 || true
}

confirm_uninstall() {
  local keep_data="$1"
  if [[ "${CHAT2API_UNINSTALL_CONFIRM:-}" == "yes" ]]; then
    return 0
  fi
  if [[ "${2:-}" == "--yes" || "${2:-}" == "-y" ]]; then
    return 0
  fi

  echo "============================================================"
  echo "  chat2api uninstall"
  echo "============================================================"
  echo "安装目录: $INSTALL_DIR"
  if [[ "$keep_data" == "1" ]]; then
    echo "操作: 停止服务，保留安装目录和数据"
  else
    echo "操作: 停止服务，并删除安装目录、/usr/local/bin/chat2api、/etc/chat2api.env"
  fi
  echo
  read -r -p 'Type "yes" to proceed: ' ans </dev/tty
  [[ "$ans" == "yes" ]]
}

resolve_uninstall_dir() {
  local resolved
  if [[ -z "${INSTALL_DIR:-}" || ! -d "$INSTALL_DIR" ]]; then
    echo "[!] Invalid INSTALL_DIR: ${INSTALL_DIR:-<empty>}" >&2
    return 1
  fi
  resolved="$(cd "$INSTALL_DIR" && pwd -P)" || return 1
  case "$resolved" in
    /|/root|/home|/Users|/opt|/srv|/tmp)
      echo "[!] Refusing to remove unsafe install directory: $resolved" >&2
      return 1
      ;;
  esac
  if [[ ! -f "$resolved/docker-compose.yml" && ! -f "$resolved/compose.yml" && ! -f "$resolved/compose.yaml" && ! -x "$resolved/deploy/multi/manage.sh" ]]; then
    echo "[!] Refusing to remove non-chat2api directory: $resolved" >&2
    return 1
  fi
  printf "%s\n" "$resolved"
}

cmd_uninstall() {
  local keep_data=0 assume_yes=0 arg install_dir_resolved
  for arg in "$@"; do
    case "$arg" in
      --keep-data) keep_data=1 ;;
      --yes|-y) assume_yes=1 ;;
      *)
        echo "Usage: chat2api uninstall [--keep-data] [--yes]"
        return 1
      ;;
    esac
  done

  install_dir_resolved="$(resolve_uninstall_dir)" || return 1

  if ! confirm_uninstall "$keep_data" "$([[ "$assume_yes" == "1" ]] && printf -- --yes)"; then
    echo "Aborted."
    return 0
  fi

  echo "[*] Stopping chat2api services..."
  if is_multi_install && is_multi_generated; then
    if ! run_multi_manage down; then
      echo "[!] Failed to stop multi-instance services; uninstall aborted."
      return 1
    fi
  elif ! stop_single_compose_if_present; then
    if is_multi_install; then
      echo "[*] Multi-instance config is not generated; removing known chat2api containers..."
      remove_known_chat2api_containers
    else
      echo "[!] Failed to stop services; uninstall aborted."
      return 1
    fi
  fi

  if [[ "$keep_data" == "1" ]]; then
    echo "[✓] Services stopped. Data kept at: $INSTALL_DIR"
    return 0
  fi

  echo "[*] Removing install directory and command..."
  cd /
  rm -rf -- "$install_dir_resolved" || as_root rm -rf -- "$install_dir_resolved"
  as_root rm -f /usr/local/bin/chat2api "$CONFIG_FILE"
  echo "[✓] chat2api uninstalled."
}

# ============================================================
# B: 模板同步（仅单实例模式）
# ============================================================
# 提取 environment 块下的 ENV 名（"      KEY: 'value'" 格式）
extract_env_keys() {
  local file="$1"
  awk '
    /^    environment:/   { in_env=1; next }
    /^    [a-z]/          { in_env=0 }
    in_env && /^      [A-Z][A-Z0-9_]*:/ {
      sub(/:.*/, "")
      sub(/^[ ]+/, "")
      print
    }
  ' "$file"
}

cmd_sync_template_check() {
  # 仅打印是否有差异，返回 0=无差异 1=有差异 2=错误
  if is_multi_install; then
    return 0
  fi
  local local_compose="$INSTALL_DIR/docker-compose.yml"
  [[ -f "$local_compose" ]] || return 2

  local tmp_template
  tmp_template="$(mktemp)" || return 2
  if ! curl -fsSL --max-time 8 "$GITHUB_RAW/deploy/docker-compose.template.yml" -o "$tmp_template" 2>/dev/null; then
    rm -f "$tmp_template"
    return 2
  fi

  local new_keys
  new_keys="$(comm -23 \
    <(extract_env_keys "$tmp_template" | sort -u) \
    <(extract_env_keys "$local_compose" | sort -u))"
  rm -f "$tmp_template"

  if [[ -z "$new_keys" ]]; then
    return 0
  fi
  echo "[i] Upstream template has new ENV keys:"
  echo "$new_keys" | sed 's/^/      + /'
  echo "[i] Run: chat2api sync-template     # to merge"
  return 1
}

cmd_sync_template() {
  if is_multi_install; then
    echo "Multi-instance mode auto-syncs via 'chat2api update' (regenerates from generate.py)."
    echo "No template sync needed."
    return 0
  fi

  local local_compose="$INSTALL_DIR/docker-compose.yml"
  if [[ ! -f "$local_compose" ]]; then
    echo "[!] $local_compose not found"
    return 1
  fi

  local tmp_template
  tmp_template="$(mktemp)"
  echo "[*] Fetching latest template from $GITHUB_RAW ..."
  if ! curl -fsSL --max-time 15 "$GITHUB_RAW/deploy/docker-compose.template.yml" -o "$tmp_template"; then
    echo "[!] Download failed"
    rm -f "$tmp_template"
    return 1
  fi

  local local_keys remote_keys new_keys removed_keys
  local_keys="$(extract_env_keys "$local_compose" | sort -u)"
  remote_keys="$(extract_env_keys "$tmp_template" | sort -u)"
  new_keys="$(comm -23 <(echo "$remote_keys") <(echo "$local_keys"))"
  removed_keys="$(comm -13 <(echo "$remote_keys") <(echo "$local_keys"))"

  if [[ -z "$new_keys" && -z "$removed_keys" ]]; then
    echo "[✓] Template already in sync."
    rm -f "$tmp_template"
    return 0
  fi

  if [[ -n "$new_keys" ]]; then
    echo "[+] New ENV keys to merge:"
    echo "$new_keys" | sed 's/^/      + /'
  fi
  if [[ -n "$removed_keys" ]]; then
    echo "[-] Local-only ENV keys (will be kept untouched):"
    echo "$removed_keys" | sed 's/^/      - /'
  fi

  if [[ -z "$new_keys" ]]; then
    rm -f "$tmp_template"
    return 0
  fi

  echo
  read -r -p "Merge new ENV keys into local docker-compose.yml? [y/N]: " ans </dev/tty
  if [[ ! "$ans" =~ ^[Yy]$ ]]; then
    rm -f "$tmp_template"
    echo "Aborted (no changes)."
    return 0
  fi

  # 备份
  local backup
  backup="${local_compose}.bak-$(date +%Y%m%d-%H%M%S)"
  cp "$local_compose" "$backup"
  echo "[*] Backed up: $backup"

  # 提取每个新 key 在 template 中的完整行（含值与缩进）
  local insert_block=""
  while IFS= read -r key; do
    [[ -z "$key" ]] && continue
    local line
    line="$(awk -v k="$key" '
      $0 ~ "^      "k":" { print; exit }
    ' "$tmp_template")"
    if [[ -n "$line" ]]; then
      insert_block+="$line"$'\n'
    fi
  done <<< "$new_keys"

  if [[ -z "$insert_block" ]]; then
    echo "[!] Could not locate new ENV lines in template; aborting."
    rm -f "$tmp_template"
    return 1
  fi

  # 在 healthcheck: 之前插入；若没有 healthcheck 则在 environment 块末尾追加
  if grep -q "^    healthcheck:" "$local_compose"; then
    awk -v block="$insert_block" '
      /^    healthcheck:/ && !inserted {
        printf "%s", block
        inserted = 1
      }
      { print }
    ' "$local_compose" > "${local_compose}.new"
  else
    awk -v block="$insert_block" '
      /^    environment:/ { in_env=1 }
      in_env && /^    [a-z]/ && !/^    environment:/ && !inserted {
        printf "%s", block
        inserted = 1
      }
      { print }
    ' "$local_compose" > "${local_compose}.new"
  fi

  mv "${local_compose}.new" "$local_compose"
  rm -f "$tmp_template"
  echo "[✓] Merged. Run 'chat2api restart' to apply."
}

# ============================================================
# D: 单实例 → 多实例迁移
# ============================================================
cmd_migrate() {
  local mode="${1:-prep}"

  if is_multi_install; then
    echo "[i] Already in multi-instance mode. Nothing to do."
    return 0
  fi

  case "$mode" in
    prep)   cmd_migrate_prep ;;
    apply)  cmd_migrate_apply ;;
    rollback) cmd_migrate_rollback "${2:-}" ;;
    *)
      echo "Usage: chat2api migrate [prep|apply|rollback <backup-dir>]"
      echo "  prep      Backup current install + generate accounts.csv (safe)"
      echo "  apply     Stop single-instance + start multi (destructive)"
      echo "  rollback  Restore from a previous backup directory"
      return 1
      ;;
  esac
}

cmd_migrate_prep() {
  local multi_dir="$INSTALL_DIR/deploy/multi"
  local backup_dir="${INSTALL_DIR}.backup-$(date +%Y%m%d-%H%M%S)"

  if [[ ! -f "$INSTALL_DIR/.env" ]]; then
    echo "[!] $INSTALL_DIR/.env not found; cannot migrate"
    return 1
  fi
  if [[ ! -d "$multi_dir" ]]; then
    echo "[!] $multi_dir not found."
    echo "    Update repo first (re-run install.sh or git pull) so deploy/multi/ exists."
    return 1
  fi

  echo "============================================================"
  echo "  chat2api migrate prep  (Single → Multi-instance)"
  echo "============================================================"
  echo "  Source:  $INSTALL_DIR (single-instance)"
  echo "  Backup:  $backup_dir"
  echo "  Multi:   $multi_dir"
  echo
  echo "[!] WARNING: This step is non-destructive (only backups + generates csv)."
  echo "    'chat2api migrate apply' is the destructive step."
  echo
  read -r -p "Continue? [y/N]: " ans </dev/tty
  [[ "$ans" =~ ^[Yy]$ ]] || { echo "Aborted."; return 0; }

  echo "[*] Backing up $INSTALL_DIR → $backup_dir ..."
  cp -a "$INSTALL_DIR" "$backup_dir"
  chmod 700 "$backup_dir" 2>/dev/null || true
  echo "[✓] Backup ready."

  local csv="$multi_dir/accounts.csv"
  local example_csv="$multi_dir/accounts.example.csv"
  local tokens_file="$INSTALL_DIR/data/token.txt"

  if [[ -f "$csv" ]]; then
    echo "[i] $csv already exists; skipping CSV generation"
  else
    echo "slug,proxy_url,note" > "$csv"
    if [[ -f "$tokens_file" ]]; then
      local count=0 i=0
      while IFS= read -r line; do
        [[ -z "$line" || "$line" =~ ^# ]] && continue
        i=$((i+1))
        printf 'acc%d,,migrated token #%d\n' "$i" "$i" >> "$csv"
        count=$i
      done < "$tokens_file"
      if [[ "$count" -eq 0 ]]; then
        echo "acc1,,migrated (please replace with real account)" >> "$csv"
        echo "[!] $tokens_file empty; created template csv with 1 placeholder"
      else
        echo "[✓] Generated $csv with $count account slot(s)"
      fi
    else
      echo "acc1,,migrated (please replace with real account)" >> "$csv"
      echo "[!] $tokens_file not found; created template csv with 1 placeholder"
    fi
  fi

  cat <<EOF

============================================================
  Next steps
============================================================

  1) Edit accounts.csv (set proxy_url, rename slugs if you want):
       \$EDITOR $csv     (or just: vi $csv)

  2) Apply migration (will stop single-instance + start multi):
       chat2api migrate apply

  3) After multi starts, import cookies/tokens via the UI Harvester
     for each new instance (data has been backed up at:
       $backup_dir/data/
     for reference / manual restore).

  Rollback at any time before apply:
       chat2api migrate rollback $backup_dir

EOF
}

cmd_migrate_apply() {
  local multi_dir="$INSTALL_DIR/deploy/multi"
  local csv="$multi_dir/accounts.csv"

  if [[ ! -f "$csv" ]]; then
    echo "[!] $csv not found. Run 'chat2api migrate prep' first."
    return 1
  fi

  echo "============================================================"
  echo "  chat2api migrate apply  (DESTRUCTIVE)"
  echo "============================================================"
  echo "  This will:"
  echo "    1. Stop and remove the single-instance container"
  echo "    2. Bring up multi-instance based on:"
  echo "         $csv"
  echo
  echo "  Current accounts.csv content:"
  echo "  --------------------------------------"
  sed 's/^/    /' "$csv"
  echo "  --------------------------------------"
  echo
  read -r -p 'Type "yes" to proceed: ' ans </dev/tty
  if [[ "$ans" != "yes" ]]; then
    echo "Aborted."
    return 0
  fi

  echo "[*] Stopping single-instance..."
  (cd "$INSTALL_DIR" && run_compose down 2>&1 | tail -5) || true

  echo "[*] Bringing up multi-instance..."
  if (cd "$multi_dir" && ./manage.sh init); then
    echo
    echo "[✓] Migration applied."
    echo "    chat2api status     # verify"
    echo "    chat2api secrets    # see new credentials"
  else
    echo "[!] manage.sh init failed; you can rollback:"
    echo "    chat2api migrate rollback <backup-dir>"
    return 1
  fi
}

cmd_migrate_rollback() {
  local backup_dir="${1:-}"
  if [[ -z "$backup_dir" ]]; then
    echo "Usage: chat2api migrate rollback <backup-dir>"
    echo
    echo "Available backups:"
    ls -d "${INSTALL_DIR}.backup-"* 2>/dev/null || echo "  (none found)"
    return 1
  fi
  if [[ ! -d "$backup_dir" ]]; then
    echo "[!] $backup_dir not found"
    return 1
  fi

  echo "[!] Rollback will:"
  echo "    1. Stop multi-instance (if running)"
  echo "    2. Restore $INSTALL_DIR from $backup_dir"
  echo "    3. Restart single-instance"
  echo
  read -r -p 'Type "yes" to proceed: ' ans </dev/tty
  [[ "$ans" == "yes" ]] || { echo "Aborted."; return 0; }

  if [[ -x "$INSTALL_DIR/deploy/multi/manage.sh" ]]; then
    (cd "$INSTALL_DIR/deploy/multi" && ./manage.sh down 2>&1 | tail -5) || true
  fi

  local trash="${INSTALL_DIR}.discarded-$(date +%Y%m%d-%H%M%S)"
  mv "$INSTALL_DIR" "$trash"
  cp -a "$backup_dir" "$INSTALL_DIR"
  echo "[*] Restored from backup; old install moved to $trash (delete after verifying)"

  (cd "$INSTALL_DIR" && run_compose up -d)
  echo "[✓] Rollback done. Run 'chat2api status' to verify."
}

# ============================================================
# Help
# ============================================================
show_help() {
  if is_multi_install; then
    cat <<'EOF'
Usage: chat2api <command>

Multi-instance commands:
  update        Re-generate config and recreate services
  start         Same as update
  restart       Same as update
  stop          Stop all multi-instance services
  uninstall     Stop and remove chat2api; use --keep-data to keep files
  status        Show multi-instance status and sampled egress IPs
  verify        Verify admin/tokens routing for all instances
  logs <slug>   Tail one instance logs
  shell <slug>  Enter one instance shell
  secrets       Print instance auth/admin secrets
  admin         Print orchestrator/admin entry hints
  path          Print install directory
  help          Show this help

Any other command is passed through to: deploy/multi/manage.sh
EOF
    return
  fi
  cat <<'EOF'
Usage: chat2api <command>

Single-instance commands:
  update              Pull latest image and recreate containers
                      (also reports if upstream template has new ENV keys)
  sync-template       Merge new ENV keys from upstream template into
                      local docker-compose.yml (interactive, makes backup)
  migrate prep        Prepare migration to multi-instance:
                      backup install dir + generate deploy/multi/accounts.csv
  migrate apply       Stop single, start multi (destructive)
  migrate rollback <backup-dir>
                      Restore single-instance from a previous backup
  restart             Restart services
  stop                Stop services
  uninstall           Stop and remove chat2api; use --keep-data to keep files
  start               Start services
  status              Show compose status
  logs                Tail chat2api logs
  admin               Print admin login URL
  api                 Print API base URL
  path                Print install directory
  help                Show this help
EOF
}

# ============================================================
# Dispatcher
# ============================================================
command_name="${1:-help}"

case "$command_name" in
  update)
    if is_multi_install; then
      update_repo_for_multi
      run_multi_manage apply
    else
      sync_deploy_assets_from_remote
      run_compose pull
      run_compose up -d
      # 提示是否有新 ENV 待合并（不强制）
      cmd_sync_template_check || true
    fi
    ;;
  sync-template)
    cmd_sync_template
    ;;
  migrate)
    cmd_migrate "${@:2}"
    ;;
  restart)
    if is_multi_install; then
      run_multi_manage apply
    else
      run_compose restart
    fi
    ;;
  stop)
    if is_multi_install; then
      run_multi_manage down
    else
      run_compose stop
    fi
    ;;
  uninstall|unstaill)
    cmd_uninstall "${@:2}"
    ;;
  start)
    if is_multi_install; then
      run_multi_manage apply
    else
      run_compose up -d
    fi
    ;;
  status)
    if is_multi_install; then
      run_multi_manage status
    else
      run_compose ps
    fi
    ;;
  logs)
    if is_multi_install; then
      run_multi_manage logs "${@:2}"
    else
      run_compose logs -f chat2api
    fi
    ;;
  shell)
    if is_multi_install; then
      run_multi_manage shell "${@:2}"
    else
      echo "shell command is only available in multi-instance mode"
      exit 1
    fi
    ;;
  verify)
    if is_multi_install; then
      run_multi_manage verify
    else
      echo "verify command is only available in multi-instance mode"
      exit 1
    fi
    ;;
  secrets)
    if is_multi_install; then
      run_multi_manage secrets
    else
      echo "secrets command is only available in multi-instance mode"
      exit 1
    fi
    ;;
  admin)
    if is_multi_install; then
      run_multi_manage secrets
    elif [[ -n "${PORT:-}" && -n "${API_PREFIX:-}" ]]; then
      echo "http://<server-ip>:${PORT}/${API_PREFIX}/admin/login"
    else
      echo "PORT/API_PREFIX not found in /etc/chat2api.env"
    fi
    ;;
  api)
    if is_multi_install; then
      run_multi_manage secrets
    elif [[ -n "${PORT:-}" && -n "${API_PREFIX:-}" ]]; then
      echo "http://<server-ip>:${PORT}/${API_PREFIX}/v1/chat/completions"
    else
      echo "PORT/API_PREFIX not found in /etc/chat2api.env"
    fi
    ;;
  path)
    echo "$INSTALL_DIR"
    ;;
  help|--help|-h)
    show_help
    ;;
  *)
    if is_multi_install; then
      run_multi_manage "$command_name" "${@:2}"
    else
      echo "Unknown command: $command_name"
      show_help
      exit 1
    fi
    ;;
esac
