#!/usr/bin/env bash
# ============================================================
# chat2api 一键部署脚本
# ============================================================
# 使用方式（新机器）：
#   curl -fsSL https://raw.githubusercontent.com/nanashiwang/chat2api/main/deploy/install.sh | bash
# 或下载后：
#   bash install.sh
#
# 本脚本默认部署多实例编排面板，会：
#   1. 自动安装 Docker（如缺）
#   2. 下载 deploy/multi 编排脚本
#   3. 启动 orchestrator 面板
#   4. 安装 chat2api 管理命令并打印访问入口
#
# 自定义环境变量（可选，脚本启动前 export 即可）：
#   INSTALL_DIR   安装目录（默认 $HOME/chat2api）
#   CHAT2API_PORT 监听端口（默认 60403）
#   GITHUB_RAW    仓库 raw URL（默认官方）
#   GITHUB_REPO   仓库 URL（默认官方，用于下载 deploy/multi）
#   CHAT2API_MODE  部署模式：multi（默认）/ single
#   INTERACTIVE   设为 1 进入交互模式（询问密码/前缀）
# ============================================================
set -euo pipefail

# ----- 颜色 -----
C_RESET="\033[0m"; C_INFO="\033[1;34m"; C_OK="\033[1;32m"
C_WARN="\033[1;33m"; C_ERR="\033[1;31m"
log()  { echo -e "${C_INFO}[*]${C_RESET} $*"; }
ok()   { echo -e "${C_OK}[✓]${C_RESET} $*"; }
warn() { echo -e "${C_WARN}[!]${C_RESET} $*"; }
err()  { echo -e "${C_ERR}[✗]${C_RESET} $*" >&2; }

# ----- 配置默认值 -----
INSTALL_DIR="${INSTALL_DIR:-$HOME/chat2api}"
GITHUB_RAW="${GITHUB_RAW:-https://raw.githubusercontent.com/nanashiwang/chat2api/main}"
GITHUB_REPO="${GITHUB_REPO:-https://github.com/nanashiwang/chat2api}"
CHAT2API_PORT="${CHAT2API_PORT:-60403}"
CHAT2API_MODE="${CHAT2API_MODE:-multi}"
INTERACTIVE="${INTERACTIVE:-0}"
SCRIPT_SOURCE="${BASH_SOURCE[0]-}"
SCRIPT_SOURCE_DIR=""
if [ -n "$SCRIPT_SOURCE" ] && [ -f "$SCRIPT_SOURCE" ]; then
    SCRIPT_SOURCE_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" 2>/dev/null && pwd || true)"
fi

# ----- sudo / root 判定 -----
if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
else
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        err "需要 root 权限或安装 sudo"
        exit 1
    fi
fi

# ----- 操作系统 -----
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS_ID="${ID,,}"
    OS_NAME="${PRETTY_NAME:-$ID}"
else
    err "无法识别操作系统（缺 /etc/os-release）"
    exit 1
fi
ok "操作系统: $OS_NAME"

# ----- 架构 -----
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64|amd64)   ARCH_DOCKER="amd64" ;;
    aarch64|arm64)  ARCH_DOCKER="arm64" ;;
    *)              err "不支持的架构: $ARCH"; exit 1 ;;
esac
ok "架构: $ARCH_DOCKER"

# ----- 依赖工具 -----
command -v curl >/dev/null 2>&1 || {
    log "安装 curl"
    case "$OS_ID" in
        ubuntu|debian) $SUDO apt-get update -qq && $SUDO apt-get install -y -qq curl ;;
        centos|rhel|rocky|almalinux) $SUDO yum install -y -q curl ;;
        *) err "请先安装 curl"; exit 1 ;;
    esac
}

# ----- 安装 Docker -----
if command -v docker >/dev/null 2>&1; then
    ok "Docker 已安装: $(docker --version | head -1)"
else
    log "Docker 未安装，使用官方脚本自动安装..."
    curl -fsSL https://get.docker.com | $SUDO sh
    $SUDO systemctl enable --now docker 2>/dev/null || true
    ok "Docker 安装完成"
fi

# ----- docker compose 插件 -----
if ! docker compose version >/dev/null 2>&1; then
    log "安装 docker compose 插件"
    case "$OS_ID" in
        ubuntu|debian) $SUDO apt-get install -y -qq docker-compose-plugin ;;
        centos|rhel|rocky|almalinux) $SUDO yum install -y -q docker-compose-plugin ;;
        *) err "docker compose 插件不可用，请手动装"; exit 1 ;;
    esac
fi
ok "docker compose 可用: $(docker compose version --short 2>/dev/null || echo installed)"

# ----- 目录 -----
log "安装目录: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR/data"
cd "$INSTALL_DIR"

# ----- 随机凭据生成 -----
gen_random() {
    local length="${1:-32}"
    LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "$length" || true
    echo
}

shell_escape() {
    printf "%s" "$1" | sed "s/'/'\\\\''/g"
}

cleanup_single_instance_for_multi() {
    if [ "$CHAT2API_MODE" != "multi" ]; then
        return 0
    fi
    if ! command -v docker >/dev/null 2>&1; then
        return 0
    fi
    if docker ps -a --format '{{.Names}}' | grep -qx 'chat2api'; then
        log "检测到旧单实例容器占用端口，先停止并移除..."
        docker rm -f chat2api >/dev/null 2>&1 || true
    fi
}

sync_deploy_assets() {
    if [ -x "$INSTALL_DIR/deploy/multi/manage.sh" ] && [ -f "$INSTALL_DIR/deploy/chat2api.sh" ]; then
        return 0
    fi

    log "准备部署辅助脚本（含多实例编排）..."
    mkdir -p "$INSTALL_DIR/deploy"

    if [ -n "$SCRIPT_SOURCE_DIR" ] && [ -d "$SCRIPT_SOURCE_DIR/multi" ]; then
        local src_deploy dest_deploy
        src_deploy="$(cd "$SCRIPT_SOURCE_DIR" 2>/dev/null && pwd -P || true)"
        dest_deploy="$(cd "$INSTALL_DIR/deploy" 2>/dev/null && pwd -P || true)"
        if [ "$src_deploy" != "$dest_deploy" ]; then
            cp -R "$SCRIPT_SOURCE_DIR"/. "$INSTALL_DIR/deploy/"
        fi
        chmod +x "$INSTALL_DIR/deploy/chat2api.sh" "$INSTALL_DIR/deploy/multi/manage.sh" 2>/dev/null || true
        ok "部署辅助脚本已准备"
        return 0
    fi

    if ! command -v tar >/dev/null 2>&1; then
        warn "tar 不可用，跳过 deploy/multi 下载；单实例部署不受影响"
        return 0
    fi

    local tmp_dir archive_dir
    tmp_dir="$(mktemp -d)" || {
        warn "临时目录创建失败，跳过 deploy/multi 下载"
        return 0
    }

    if curl -fsSL "${GITHUB_REPO}/archive/refs/heads/main.tar.gz" | tar -xz -C "$tmp_dir"; then
        archive_dir="$(find "$tmp_dir" -maxdepth 1 -type d -name 'chat2api-*' | head -1)"
        if [ -n "$archive_dir" ] && [ -d "$archive_dir/deploy" ]; then
            cp -R "$archive_dir/deploy"/. "$INSTALL_DIR/deploy/"
            chmod +x "$INSTALL_DIR/deploy/chat2api.sh" "$INSTALL_DIR/deploy/multi/manage.sh" 2>/dev/null || true
            ok "部署辅助脚本已准备（含 deploy/multi）"
        else
            warn "仓库包缺少 deploy/，跳过 deploy/multi 下载"
        fi
    else
        warn "deploy/multi 下载失败；单实例部署不受影响"
    fi
    rm -rf "$tmp_dir"
}

install_manage_command() {
    local script_src tmp_script

    script_src=""
    if [ -n "$SCRIPT_SOURCE_DIR" ] && [ -f "$SCRIPT_SOURCE_DIR/chat2api.sh" ]; then
        script_src="${SCRIPT_SOURCE_DIR}/chat2api.sh"
    elif [ -f "$INSTALL_DIR/deploy/chat2api.sh" ]; then
        script_src="$INSTALL_DIR/deploy/chat2api.sh"
    fi

    $SUDO mkdir -p /etc || return 1
    if ! $SUDO tee /etc/chat2api.env >/dev/null <<EOF
INSTALL_DIR='$(shell_escape "$INSTALL_DIR")'
PORT='$(shell_escape "$CHAT2API_PORT")'
API_PREFIX='$(shell_escape "$API_PREFIX")'
EOF
    then
        return 1
    fi

    if [ -n "$script_src" ] && [ -f "$script_src" ]; then
        $SUDO install -m 0755 "$script_src" /usr/local/bin/chat2api || return 1
    else
        tmp_script="$(mktemp)" || return 1
        curl -fsSL "$GITHUB_RAW/deploy/chat2api.sh" -o "$tmp_script" || {
            rm -f "$tmp_script"
            return 1
        }
        $SUDO install -m 0755 "$tmp_script" /usr/local/bin/chat2api || {
            rm -f "$tmp_script"
            return 1
        }
        rm -f "$tmp_script"
    fi
}

sync_deploy_assets
cleanup_single_instance_for_multi

if [ "$CHAT2API_MODE" = "multi" ]; then
    if [ ! -x "$INSTALL_DIR/deploy/multi/manage.sh" ]; then
        err "deploy/multi 未准备好，请检查网络后重试"
        exit 1
    fi

    log "启动多实例编排面板..."
    (
        cd "$INSTALL_DIR/deploy/multi"
        CHAT2API_GATEWAY_PORT="$CHAT2API_PORT" ./manage.sh init
        ./manage.sh install-cli
    )

    PUBLIC_IP="$(curl -fsSL --max-time 5 https://api.ipify.org 2>/dev/null || \
                 curl -fsSL --max-time 5 https://ifconfig.me 2>/dev/null || \
                 echo 'your-server-ip')"

cat <<EOF

============================================================
✅ chat2api 多实例编排面板已部署完成
============================================================

📍 访问:
   编排面板:  http://${PUBLIC_IP}:${CHAT2API_PORT}/orchestrator/

🔑 密码:
   查看命令:  cd ${INSTALL_DIR}/deploy/multi && ./manage.sh secrets

📖 下一步:
   1. 打开编排面板
   2. 点「新增账号」
   3. 填 slug / 代理 / 备注
   4. 进入对应实例后台粘贴 Cookie

📋 常用命令:
   chat2api update
   chat2api status
   chat2api secrets

============================================================

EOF
    exit 0
fi

# ----- 下载 compose 模板 -----
if [ -f docker-compose.yml ]; then
    warn "docker-compose.yml 已存在，跳过下载"
else
    log "下载 docker-compose.yml 模板"
    if ! curl -fsSL "$GITHUB_RAW/deploy/docker-compose.template.yml" -o docker-compose.yml; then
        err "下载失败，请检查 GITHUB_RAW 变量或网络"
        exit 1
    fi
    ok "模板下载完成"
fi

# ----- 生成或复用 .env -----
if [ -f .env ]; then
    warn ".env 已存在，沿用现有配置"
    set +u; . ./.env; set -u
else
    log "生成随机凭据..."
    if [ "$INTERACTIVE" = "1" ]; then
        read -r -p "管理员密码 [留空自动生成 24 位]: " INPUT_ADMIN_PWD
        ADMIN_PASSWORD="${INPUT_ADMIN_PWD:-$(gen_random 24)}"
        read -r -p "API 密钥 [留空自动生成 sk-...]: " INPUT_AUTH
        AUTHORIZATION="${INPUT_AUTH:-sk-$(gen_random 32)}"
        read -r -p "API 路径前缀 [留空自动生成 api-...]: " INPUT_PREFIX
        API_PREFIX="${INPUT_PREFIX:-api-$(gen_random 12)}"
    else
        ADMIN_PASSWORD="$(gen_random 24)"
        AUTHORIZATION="sk-$(gen_random 32)"
        API_PREFIX="api-$(gen_random 12)"
    fi

    cat > .env <<EOF
# ============ chat2api 自动生成凭据 · 勿入 git ============
ADMIN_PASSWORD=${ADMIN_PASSWORD}
AUTHORIZATION=${AUTHORIZATION}
API_PREFIX=${API_PREFIX}

TZ=Asia/Shanghai
CHAT2API_PORT=${CHAT2API_PORT}

# ============ 可选安全加固 ============
# 管理后台 IP 白名单（强烈建议配置，限制访问源）
# ADMIN_IP_WHITELIST=1.2.3.4,10.0.0.0/8
# ADMIN_TRUST_PROXY=true

# ============ 代理（可选，优先在 UI 的"代理与路由"添加） ============
# PROXY_URL=
# EXPORT_PROXY_URL=
EOF
    chmod 600 .env
    ok ".env 已生成，权限 600"
fi

# ----- 启动 -----
log "拉取镜像并启动..."
$SUDO docker compose pull -q 2>&1 | grep -v "^$" || true
$SUDO docker compose up -d

# ----- 宿主管理命令 -----
log "安装管理命令..."
if install_manage_command; then
    ok "管理命令已安装: chat2api update"
else
    warn "管理命令安装失败；服务已启动，可先用 docker compose pull && docker compose up -d 更新"
fi

# ----- 健康检查 -----
log "等待服务就绪..."
for i in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${CHAT2API_PORT}/${API_PREFIX}/admin/login" > /dev/null 2>&1; then
        ok "服务就绪（第 ${i} 秒）"
        break
    fi
    if [ "$i" -eq 60 ]; then
        warn "服务 60 秒内未响应，检查日志: cd $INSTALL_DIR && docker compose logs"
    fi
    sleep 1
done

# ----- 公网 IP 获取 -----
PUBLIC_IP="$(curl -fsSL --max-time 5 https://api.ipify.org 2>/dev/null || \
             curl -fsSL --max-time 5 https://ifconfig.me 2>/dev/null || \
             echo 'your-server-ip')"

# ----- 结果摘要 -----
cat <<EOF

============================================================
✅ chat2api 单实例部署完成
============================================================

📍 访问:
   管理后台:  http://${PUBLIC_IP}:${CHAT2API_PORT}/${API_PREFIX}/admin/login
   API:        http://${PUBLIC_IP}:${CHAT2API_PORT}/${API_PREFIX}/v1/chat/completions

🔑 凭据（保存在 ${INSTALL_DIR}/.env · chmod 600）:
   ADMIN_PASSWORD:  ${ADMIN_PASSWORD}
   AUTHORIZATION:   ${AUTHORIZATION}
   API_PREFIX:      ${API_PREFIX}

📖 下一步:
   1. 登录管理后台
   2. "账号采集 Harvester" → 新增账号 → 🍪 粘贴 Cookie
      （在本地浏览器登录 chatgpt.com，F12 Console 执行:
       document.cookie.split(';').filter(x=>x.includes('session-token')).join('; ')
       复制结果粘到 UI）
   3. "代理与路由"（可选）→ 添加住宅代理 → 给账号绑定
   4. 测试: curl -H "Authorization: Bearer ${AUTHORIZATION}" \\
            http://localhost:${CHAT2API_PORT}/${API_PREFIX}/v1/models

🛡️  安全加固（强烈建议）:
   - 配置 IP 白名单:
     vim ${INSTALL_DIR}/.env
     ADMIN_IP_WHITELIST=你的办公/家庭 IP
     chat2api restart
   - 或接入 Cloudflare 免费版隐藏真实 IP
   - 详见: ${GITHUB_RAW}/docs/SECURITY.md

📋 常用命令:
   chat2api status                  # 查看状态
   chat2api logs                    # 实时日志
   chat2api restart                 # 重启
   chat2api update                  # 升级
   chat2api stop                    # 停止

============================================================

EOF
