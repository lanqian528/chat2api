#!/usr/bin/env bash
# chat2api 多实例运维包装（KISS）
# 全部子命令幂等：底层都是 generate.py + docker compose
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

C_RESET="\033[0m"; C_INFO="\033[1;34m"; C_OK="\033[1;32m"; C_ERR="\033[1;31m"
log()  { echo -e "${C_INFO}[*]${C_RESET} $*"; }
ok()   { echo -e "${C_OK}[\u2713]${C_RESET} $*"; }
err()  { echo -e "${C_ERR}[\u2717]${C_RESET} $*" >&2; }

CSV="$DIR/accounts.csv"
EXAMPLE_CSV="$DIR/accounts.example.csv"
GEN_DIR="$DIR/generated"
COMPOSE="$GEN_DIR/docker-compose.yml"
REPO_ROOT="$(cd "$DIR/../.." && pwd)"

# orchestrator 必需：让容器内的 docker compose --project-directory 指向宿主路径
export MULTI_HOST_PATH="$DIR"

ensure_csv() {
    if [ ! -f "$CSV" ]; then
        printf 'slug,proxy_url,note\n' > "$CSV"
        log "已创建空 accounts.csv；可在编排面板里新增账号"
    fi
}

require_compose() {
    if [ ! -f "$COMPOSE" ]; then
        err "尚未生成，请先 ./manage.sh init"
        exit 1
    fi
}

dc() {
    docker compose -f "$COMPOSE" --project-directory "$DIR" "$@"
}

compose_up() {
    if dc up -d --remove-orphans --pull missing "$@"; then
        return 0
    fi
    log "镜像拉取失败，尝试使用本地已有镜像继续..."
    dc up -d --remove-orphans --pull never "$@"
}

slugs() {
    awk -F, 'NR>1 && $1!="" {print $1}' "$CSV"
}

as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        err "需要 root 权限或已安装 sudo"
        exit 1
    fi
}

public_host() {
    curl -fsSL --max-time 5 https://api.ipify.org 2>/dev/null \
        || curl -fsSL --max-time 5 https://ifconfig.me 2>/dev/null \
        || printf '<vps>'
}

orch_password() {
    awk -F= '$1=="ORCH_PASSWORD"{print $2}' "$GEN_DIR/orch.env" 2>/dev/null | tail -1
}

orch_api_key() {
    awk -F= '$1=="ORCH_API_KEY"{print $2}' "$GEN_DIR/orch.env" 2>/dev/null | tail -1
}

cmd_access_summary() {
    [ -f "$GEN_DIR/orch.env" ] || return 0
    local port host orch_pwd
    port="${CHAT2API_GATEWAY_PORT:-60403}"
    host="$(public_host)"
    orch_pwd="$(orch_password)"
    cat <<EOF

============================================================
多实例编排面板（管理所有容器）
============================================================
URL:            http://${host}:${port}/orchestrator/
ORCH_PASSWORD:  ${orch_pwd:-见 $GEN_DIR/orch.env}

统一 API:
  BASE_URL:     http://${host}:${port}/v1
  API_KEY:      $(orch_api_key)

单个实例后台 / API 凭证:
  ./manage.sh secrets
============================================================

EOF
}

cleanup_renamed_containers() {
    local ids
    ids="$(docker ps -a --format '{{.ID}} {{.Names}}' \
        | awk '$2 ~ /^[0-9a-f]+_c2a-/ {print $1}')"
    if [ -n "$ids" ]; then
        log "清理上次重建残留容器..."
        # shellcheck disable=SC2086
        docker rm -f $ids >/dev/null 2>&1 || true
    fi
}

auto_pull() {
    # cmd_apply 前自动 git pull --ff-only。
    # 有本地跟踪文件改动时自动 stash，避免旧部署脚本挡住更新。
    # 设计原则：永不 reset；本地改动只暂存到 git stash，方便需要时找回。
    if [ "${NO_PULL:-0}" = "1" ]; then
        log "NO_PULL=1，跳过 git pull"
        return 0
    fi
    local repo_root
    if ! repo_root="$(git -C "$DIR" rev-parse --show-toplevel 2>/dev/null)"; then
        log "非 git 仓库，由 chat2api update 负责同步部署文件"
        return 0
    fi
    local branch
    branch="$(git -C "$repo_root" rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)"
    if [ "$branch" = "HEAD" ]; then
        log "detached HEAD，跳过 git pull（手动 checkout 分支后再 update）"
        return 0
    fi
    local stash_msg=""
    if [ -n "$(git -C "$repo_root" status --porcelain 2>/dev/null)" ]; then
        stash_msg="chat2api auto-stash before update $(date -u +%Y%m%dT%H%M%SZ)"
        log "检测到本地改动，自动暂存到 git stash..."
        if git -C "$repo_root" stash push -m "$stash_msg" -- . >/dev/null 2>&1; then
            ok "本地改动已暂存：$stash_msg"
        else
            log "自动暂存失败，跳过 git pull（可手动处理后重试）"
            return 0
        fi
    fi
    log "git pull --ff-only ($branch)..."
    if git -C "$repo_root" pull --ff-only --quiet 2>/dev/null; then
        ok "代码已同步到 $(git -C "$repo_root" log -1 --pretty='%h %s')"
        if [ -n "$stash_msg" ]; then
            log "如需查看被暂存的本地改动：git -C \"$repo_root\" stash list"
        fi
    else
        if [ -n "$stash_msg" ]; then
            git -C "$repo_root" stash pop --quiet >/dev/null 2>&1 || true
        fi
        log "git pull 跳过（非 fast-forward 或远端不可达），继续用当前版本"
    fi
}

cmd_apply() {
    auto_pull
    ensure_csv
    log "生成配置..."
    python3 "$DIR/generate.py"
    cleanup_renamed_containers
    local has_orchestrator=0
    if dc config --services 2>/dev/null | grep -qx orchestrator; then
        has_orchestrator=1
        log "构建 orchestrator 镜像..."
        dc build orchestrator
    fi
    log "应用 docker compose..."
    if [ "$has_orchestrator" -eq 1 ]; then
        # orchestrator 是本地 build 镜像，静态文件变更后必须替换容器才能加载新面板。
        compose_up --force-recreate orchestrator
    fi
    compose_up
    # nginx.conf 变化时 compose 不会重启 nginx，主动 reload
    if docker ps --format '{{.Names}}' | grep -qx c2a-nginx; then
        docker exec c2a-nginx nginx -s reload 2>/dev/null \
            && log "nginx reload OK" \
            || log "nginx reload 失败（首次启动可忽略）"
    fi
    cmd_verify
    if [ "$has_orchestrator" -eq 1 ]; then
        cmd_verify_orchestrator
        cmd_access_summary
    fi
    ok "完成。优先使用上面的编排面板管理所有容器。"
}

cmd_init() {
    cmd_apply
}

cmd_add() {
    local slug="${1:-}" proxy="${2:-}" note="${3:-}"
    if [ -z "$slug" ]; then
        err "用法: ./manage.sh add <slug> [proxy_url] [note]"
        exit 1
    fi
    ensure_csv
    if grep -q "^${slug}," "$CSV" 2>/dev/null; then
        err "slug='$slug' 已存在于 accounts.csv"
        exit 1
    fi
    echo "${slug},${proxy},${note}" >> "$CSV"
    ok "已追加到 accounts.csv: $slug"
    cmd_apply
}

cmd_remove() {
    local slug="${1:-}"
    if [ -z "$slug" ]; then
        err "用法: ./manage.sh remove <slug>"
        exit 1
    fi
    ensure_csv
    if ! grep -q "^${slug}," "$CSV"; then
        err "slug='$slug' 不在 accounts.csv 中"
        exit 1
    fi
    log "停止并清理容器 c2a-${slug}..."
    if [ -f "$COMPOSE" ]; then
        dc stop "chat2api-${slug}" 2>/dev/null || true
        dc rm -f "chat2api-${slug}" 2>/dev/null || true
    fi
    log "从 accounts.csv 移除..."
    grep -v "^${slug}," "$CSV" > "$CSV.tmp" && mv "$CSV.tmp" "$CSV"
    log "保留 data/${slug}/ 目录（如确认无用，请手动 rm -rf）"
    cmd_apply
}

cmd_list() {
    require_compose
    dc ps
}

cmd_logs() {
    local slug="${1:-}" tail="${2:-200}"
    if [ -z "$slug" ]; then
        err "用法: ./manage.sh logs <slug> [行数]"
        exit 1
    fi
    docker logs --tail "$tail" -f "c2a-${slug}"
}

cmd_shell() {
    local slug="${1:-}"
    if [ -z "$slug" ]; then
        err "用法: ./manage.sh shell <slug>"
        exit 1
    fi
    docker exec -it "c2a-${slug}" sh
}

cmd_secrets() {
    if [ ! -f "$GEN_DIR/secrets.txt" ]; then
        err "secrets.txt 不存在，先 ./manage.sh init"
        exit 1
    fi
    cat "$GEN_DIR/secrets.txt"
    if [ -f "$GEN_DIR/orch.env" ]; then
        echo
        echo "============ Orchestrator 编排面板（管理所有容器） ============"
        grep '^ORCH_USERNAME=' "$GEN_DIR/orch.env" 2>/dev/null \
            | sed 's/^/  /'
        grep '^ORCH_PASSWORD=' "$GEN_DIR/orch.env" 2>/dev/null \
            | sed 's/^/  /'
        local port="${CHAT2API_GATEWAY_PORT:-60403}"
        local host
        host="$(public_host)"
        echo "  URL: http://${host}:${port}/orchestrator/"
        echo
        echo "============ 统一 API（自动均衡所有实例） ============"
        grep '^ORCH_API_KEY=' "$GEN_DIR/orch.env" 2>/dev/null \
            | sed 's/^/  /'
        echo "  BASE_URL: http://${host}:${port}/v1"
        echo "  CHAT:     http://${host}:${port}/v1/chat/completions"
        echo "==============================================="
    fi
}

cmd_orch_password() {
    if [ ! -f "$GEN_DIR/orch.env" ]; then
        err "orch.env 不存在；先 ./manage.sh init 生成"
        exit 1
    fi
    local new_pwd
    if [ -n "${1:-}" ]; then
        new_pwd="$1"
    else
        new_pwd=$(python3 -c 'import secrets,string; print("".join(secrets.choice(string.ascii_letters+string.digits) for _ in range(24)))')
    fi
    awk -v new="$new_pwd" '/^ORCH_PASSWORD=/{print "ORCH_PASSWORD="new; next} {print}' \
        "$GEN_DIR/orch.env" > "$GEN_DIR/orch.env.tmp"
    mv "$GEN_DIR/orch.env.tmp" "$GEN_DIR/orch.env"
    chmod 600 "$GEN_DIR/orch.env"
    log "已写入新 ORCH_PASSWORD，强制重建 orchestrator（让 env_file 重新加载）..."
    dc up -d --force-recreate orchestrator
    ok "新密码：$new_pwd"
    log "提示：HMAC SESSION_SECRET 未变，旧 cookie 仍有效到 8h 过期；如需立刻全部失效，编辑 orch.env 改 ORCH_SESSION_SECRET 后再次重建"
}

cmd_down() {
    require_compose
    dc down
    ok "已停止所有实例（数据保留）"
}

cmd_status() {
    require_compose
    log "容器状态:"
    dc ps
    echo
    log "出口 IP 抽样（前 5 个实例）:"
    local count=0
    for s in $(awk -F, 'NR>1 && $1!="" {print $1}' "$CSV"); do
        [ "$count" -ge 5 ] && break
        printf "  %-12s -> " "$s"
        docker exec "c2a-${s}" curl -s --max-time 8 https://api.ipify.org 2>/dev/null \
            || echo "(unreachable)"
        echo
        count=$((count+1))
    done
}

check_contains() {
    local url="$1" needle="$2" tries="${3:-8}" body=""
    local i
    for i in $(seq 1 "$tries"); do
        body="$(curl -fsS --max-time 15 "$url" 2>/dev/null || true)"
        if printf '%s' "$body" | grep -q "$needle"; then
            return 0
        fi
        sleep 1
    done
    printf '%s' "$body"
    return 1
}

cmd_verify() {
    require_compose
    ensure_csv
    local port="${CHAT2API_GATEWAY_PORT:-60403}"
    local failed=0 slug env_prefix container_prefix nginx_block admin_out tokens_out
    log "校验路由与后台页面..."
    for slug in $(slugs); do
        env_prefix="$(awk -F= '$1=="API_PREFIX"{print $2}' "$GEN_DIR/env/${slug}.env" 2>/dev/null | tail -1)"
        container_prefix="$(docker exec "c2a-${slug}" sh -lc 'printf %s "${API_PREFIX:-}"' 2>/dev/null || true)"
        if [ -z "$env_prefix" ] || [ "$env_prefix" != "$container_prefix" ]; then
            err "${slug}: API_PREFIX 不一致（env=${env_prefix:-<empty>} container=${container_prefix:-<empty>}）"
            failed=1
            continue
        fi

        nginx_block="$(docker exec c2a-nginx nginx -T 2>/dev/null | grep -A8 "location /${slug}/" || true)"
        if ! printf '%s\n' "$nginx_block" | grep -q "$env_prefix"; then
            err "${slug}: nginx 生效配置未指向 ${env_prefix}"
            failed=1
            continue
        fi

        if ! admin_out="$(check_contains "http://127.0.0.1:${port}/${slug}/admin/login" '管理后台登录\|<title>Admin Login</title>')"; then
            err "${slug}: admin/login 校验失败"
            printf '%s\n' "$admin_out" | head -3
            failed=1
            continue
        fi

        if ! tokens_out="$(check_contains "http://127.0.0.1:${port}/${slug}/tokens" '<title>Tokens 管理</title>')"; then
            err "${slug}: /tokens 校验失败"
            printf '%s\n' "$tokens_out" | head -3
            failed=1
            continue
        fi

        ok "${slug}: admin/tokens 正常"
    done

    if [ "$failed" -ne 0 ]; then
        err "校验失败：请先处理上面的实例"
        return 1
    fi
}

cmd_verify_orchestrator() {
    require_compose
    local port="${CHAT2API_GATEWAY_PORT:-60403}"
    local js_out app_out models_out
    log "校验 orchestrator 静态资源..."
    if ! js_out="$(check_contains "http://127.0.0.1:${port}/orchestrator/static/app.js" 'pg-custom-model' 6)"; then
        err "orchestrator: app.js 仍是旧版本（缺少 Playground 自定义模型代码）"
        printf '%s\n' "$js_out" | head -3
        return 1
    fi
    if ! app_out="$(docker exec c2a-orchestrator grep -q 'X-Chat2API-Stream-Compat' /app/app.py 2>&1)"; then
        err "orchestrator: app.py 仍是旧版本（缺少统一入口流式兼容代码）"
        printf '%s\n' "$app_out" | head -3
        return 1
    fi
    if ! models_out="$(check_contains "http://127.0.0.1:${port}/orchestrator/static/models_by_plan.json" '"plans"' 6)"; then
        err "orchestrator: models_by_plan.json 不可访问"
        printf '%s\n' "$models_out" | head -3
        return 1
    fi
    ok "orchestrator: 模型看板静态资源正常"
}

cmd_install_cli() {
    local config_tmp
    config_tmp="$(mktemp)"
    cat > "$config_tmp" <<EOF
INSTALL_DIR='$REPO_ROOT'
EOF
    as_root mkdir -p /etc
    as_root cp "$config_tmp" /etc/chat2api.env
    rm -f "$config_tmp"
    as_root install -m 0755 "$REPO_ROOT/deploy/chat2api.sh" /usr/local/bin/chat2api
    ok "已安装 /usr/local/bin/chat2api"
    log "现在可直接使用: chat2api status / chat2api update / chat2api verify"
}

cmd_help() {
    cat <<'EOF'
chat2api 多实例运维（一容器一账号）

用法:
  ./manage.sh init                          首次部署（启动编排面板；账号可在 UI 新增）
  ./manage.sh apply                         重新生成配置并应用
  ./manage.sh add <slug> [proxy] [note]     追加单个账号 + apply
  ./manage.sh remove <slug>                 移除单个账号 + apply（保留 data/）
  ./manage.sh list                          所有容器状态（docker compose ps）
  ./manage.sh status                        状态 + 抽样验证出口 IP
  ./manage.sh verify                        校验每个实例的后台/路由是否串线
  ./manage.sh verify-orchestrator           校验编排面板模型看板静态资源
  ./manage.sh logs <slug> [N]               跟随该实例日志（默认 200 行）
  ./manage.sh shell <slug>                  进入该实例容器 shell
  ./manage.sh secrets                       打印所有 AUTH / ADMIN_PWD（敏感）
  ./manage.sh orch-password [pwd]           重置编排面板密码（不传则随机生成）
  ./manage.sh install-cli                   安装全局 chat2api 命令
  ./manage.sh down                          停止全部（数据保留）
  ./manage.sh help                          显示本帮助

环境变量（可选）:
  CHAT2API_GATEWAY_PORT  nginx 对外端口（默认 60403）
  CHAT2API_IMAGE         覆盖镜像（默认 ghcr.io/nanashiwang/chat2api:latest）

文件:
  accounts.csv           真实账号清单（敏感，git 忽略）
  generated/             生成产物（含密钥，git 忽略）
  data/<slug>/           每实例数据卷（含 cookie/token，git 忽略）
EOF
}

cmd="${1:-help}"
shift || true
case "$cmd" in
    init)    cmd_init "$@" ;;
    apply)   cmd_apply "$@" ;;
    add)     cmd_add "$@" ;;
    remove)  cmd_remove "$@" ;;
    list)    cmd_list "$@" ;;
    status)  cmd_status "$@" ;;
    verify)  cmd_verify "$@" ;;
    verify-orchestrator) cmd_verify_orchestrator "$@" ;;
    logs)    cmd_logs "$@" ;;
    shell)   cmd_shell "$@" ;;
    secrets) cmd_secrets "$@" ;;
    orch-password) cmd_orch_password "$@" ;;
    install-cli) cmd_install_cli "$@" ;;
    down)    cmd_down "$@" ;;
    help|-h|--help) cmd_help ;;
    *) err "未知命令: $cmd"; cmd_help; exit 1 ;;
esac
