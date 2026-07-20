#!/usr/bin/env python3
"""chat2api 多实例部署生成器（KISS / YAGNI / DRY）

输入：./accounts.csv      [slug, proxy_url, note]
输出：./generated/docker-compose.yml
      ./generated/nginx.conf
      ./generated/env/<slug>.env
      ./generated/secrets.txt   (chmod 600)
      ./data/<slug>/            (空目录，作为容器数据卷)

设计要点：
1. 纯标准库（stdlib），无 jinja2 依赖
2. 已有 env 文件中的 AUTHORIZATION/ADMIN_PASSWORD/API_PREFIX 复用，避免重生成导致客户端 key 失效
3. 每实例独立 SOCKS5 代理（可空）；空时 PROXY_URL 不写入
4. 不映射 chat2api 实例的宿主端口，仅 nginx 暴露 60403
"""
from __future__ import annotations

import csv
import os
import re
import secrets as pysecrets
import string
import sys
from pathlib import Path
from typing import Iterator, NamedTuple

ROOT = Path(__file__).resolve().parent
CSV_FILE = ROOT / "accounts.csv"
GEN_DIR = ROOT / "generated"
ENV_DIR = GEN_DIR / "env"
DATA_DIR = ROOT / "data"
SECRETS_FILE = GEN_DIR / "secrets.txt"
COMPOSE_FILE = GEN_DIR / "docker-compose.yml"
NGINX_FILE = GEN_DIR / "nginx.conf"
ORCH_ENV = GEN_DIR / "orch.env"

SLUG_RE = re.compile(r"^[a-z0-9-]{1,16}$")
PROXY_RE = re.compile(r"^(socks5|socks5h|http|https)://[^\s]+$")

NGINX_PORT = int(os.environ.get("CHAT2API_GATEWAY_PORT", "60403"))
CHAT2API_IMAGE = os.environ.get(
    "CHAT2API_IMAGE", "ghcr.io/nanashiwang/chat2api:latest"
)
WATCHTOWER_IMAGE = os.environ.get(
    "WATCHTOWER_IMAGE", "nickfedor/watchtower:latest"
)
ORCH_ENABLED = os.environ.get("ORCH_ENABLED", "true").lower() != "false"


class Account(NamedTuple):
    slug: str
    proxy_url: str
    note: str
    auth: str
    admin_password: str
    api_prefix: str


# ---------- helpers ----------

def fail(msg: str) -> None:
    sys.stderr.write(f"\033[1;31m[!]\033[0m {msg}\n")
    sys.exit(1)


def info(msg: str) -> None:
    sys.stdout.write(f"\033[1;34m[*]\033[0m {msg}\n")


def ok(msg: str) -> None:
    sys.stdout.write(f"\033[1;32m[\u2713]\033[0m {msg}\n")


def gen_auth() -> str:
    return "sk-" + pysecrets.token_hex(16)


def gen_admin_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(pysecrets.choice(alphabet) for _ in range(24))


def gen_api_prefix() -> str:
    return "api-" + pysecrets.token_hex(4)


def parse_env_file(path: Path) -> dict[str, str]:
    """简易 .env 解析：KEY=VALUE，忽略 # 注释与空行；不解析 quote。"""
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def read_csv() -> list[tuple[str, str, str]]:
    if not CSV_FILE.exists():
        fail(f"未找到 {CSV_FILE}；请基于 accounts.example.csv 创建")
    rows: list[tuple[str, str, str]] = []
    with CSV_FILE.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"slug", "proxy_url", "note"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            fail(f"CSV 表头必须包含: {sorted(required)}")
        seen: set[str] = set()
        for i, row in enumerate(reader, start=2):
            slug = (row.get("slug") or "").strip()
            proxy = (row.get("proxy_url") or "").strip()
            note = (row.get("note") or "").strip()
            if not slug:
                continue  # 跳过空行
            if not SLUG_RE.match(slug):
                fail(f"第 {i} 行 slug='{slug}' 不合法（需 [a-z0-9-]{{1,16}}）")
            if slug in seen:
                fail(f"第 {i} 行 slug='{slug}' 重复")
            seen.add(slug)
            if proxy and not PROXY_RE.match(proxy):
                fail(f"第 {i} 行 proxy_url='{proxy}' 不合法")
            rows.append((slug, proxy, note))
    if not rows:
        info("CSV 暂无账号，仅启动 orchestrator + nginx + watchtower（可在面板内增加）")
    return rows


def resolve_secrets(slug: str) -> tuple[str, str, str]:
    """已有 env 优先复用其密钥，否则生成新值。"""
    env = parse_env_file(ENV_DIR / f"{slug}.env")
    auth = env.get("AUTHORIZATION") or gen_auth()
    pwd = env.get("ADMIN_PASSWORD") or gen_admin_password()
    prefix = env.get("API_PREFIX") or gen_api_prefix()
    return auth, pwd, prefix


def load_accounts() -> list[Account]:
    out: list[Account] = []
    for slug, proxy, note in read_csv():
        auth, pwd, prefix = resolve_secrets(slug)
        out.append(Account(slug, proxy, note, auth, pwd, prefix))
    return out


# ---------- renderers ----------

ENV_TEMPLATE = """\
# 自动生成 — 由 generate.py 维护，请勿手工修改
AUTHORIZATION={auth}
ADMIN_PASSWORD={admin_password}
API_PREFIX={api_prefix}
"""


def render_env(acc: Account) -> str:
    body = ENV_TEMPLATE.format(
        auth=acc.auth,
        admin_password=acc.admin_password,
        api_prefix=acc.api_prefix,
    )
    if acc.proxy_url:
        body += f"PROXY_URL={acc.proxy_url}\n"
    return body


COMPOSE_HEADER = """\
# 自动生成 — 由 generate.py 维护，请勿手工修改
# 来源：deploy/multi/accounts.csv

x-chat2api-common: &c2a-common
  image: {image}
  restart: unless-stopped
  pull_policy: always
  networks: [c2a-net]
  labels:
    com.centurylinklabs.watchtower.enable: 'true'
  # 资源/权限边界：单实例故障不污染母机与同行容器
  cap_drop: [ALL]
  security_opt:
    - no-new-privileges:true
  pids_limit: 200
  mem_limit: 512m
  cpus: '0.5'
  environment:
    TZ: 'Asia/Shanghai'
    CHATGPT_BASE_URL: 'https://chatgpt.com'
    HISTORY_DISABLED: 'true'
    SCHEDULED_REFRESH: 'true'
    ENABLE_LIMIT: 'true'
    OAI_LANGUAGE: 'zh-CN'
    ENABLE_GATEWAY: 'true'
    AUTO_SEED: 'true'
    RANDOM_TOKEN: 'false'
    RETRY_TIMES: '3'
    # 一容器一账号 + 独立住宅 IP：默认开启风控规避层并强制 IP 绑定
    ENABLE_ANTIBAN: 'true'
    STRICT_IP_BINDING: 'true'
    BUCKET_MAX_ACCOUNTS_PER_IP: '1'
    # 账号级冷却已关闭（一容器一账号，外部客户端节奏决定 QPS）；
    # 429/403 熔断退避走 CIRCUIT_* 独立路径，不受影响。
    ACCOUNT_MIN_INTERVAL_SECONDS: '0'
    FREE_ACCOUNT_MIN_INTERVAL_SECONDS: '0'
    ACCOUNT_COOLDOWN_JITTER: '0.3'
    ACCOUNT_MAX_WAIT_SECONDS: '30'
    IP_GEO_PROVIDER: 'ip-api'
    CIRCUIT_429_COOLDOWN: '1800'
    CIRCUIT_403_COOLDOWN: '3600'
    CIRCUIT_BUCKET_HEAL_MINUTES: '30'
    INIT_APPLY_ON_EMPTY: 'true'
    LOG_BUFFER_SIZE: '3000'
    # Session Sticky (LibreChat → New-API → chat2api 链路下的窗口级会话续接)
    # 默认开启：依赖 LibreChat 在 request body 注入 librechat_conversation_id（librechat.yaml addParams）
    # 与 New-API 的 Channel Affinity（同 lc_conv_id 永远命中同一渠道）协作；不会影响不带该字段的请求
    ENABLE_SESSION_STICKY: 'true'
    SESSION_TTL_DAYS: '30'
    SESSION_LC_FIELD: 'librechat_conversation_id'
    SESSION_TRIM_TO_LAST_USER: 'true'

services:
"""

COMPOSE_INSTANCE = """\
  chat2api-{slug}:
    <<: *c2a-common
    container_name: c2a-{slug}
    env_file:
      - ./generated/env/{slug}.env
    volumes:
      - ./data/{slug}:/app/data
    healthcheck:
      # 镜像不含 curl，用 python TCP 探活 5005 端口（最简存活检查）
      test: ["CMD", "python", "-c", "import socket; s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1',5005)); s.close()"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s

"""

COMPOSE_ORCHESTRATOR = """\
  orchestrator:
    image: c2a-orchestrator:local
    build:
      context: ./orchestrator
    container_name: c2a-orchestrator
    restart: unless-stopped
    networks: [c2a-net]
    env_file:
      - ./generated/orch.env
    environment:
      MULTI_HOST_PATH: '{host_path}'
      ORCH_PORT: '8080'
      TZ: 'Asia/Shanghai'
    # 关键：用宿主路径作为容器内挂载点，让 docker compose 客户端
    # （在容器内运行）与 daemon（在宿主运行）能用同一路径找到 env_file 与 volumes
    volumes:
      - '{host_path}:{host_path}'
      - /var/run/docker.sock:/var/run/docker.sock
    labels:
      com.centurylinklabs.watchtower.enable: 'true'

"""

COMPOSE_FOOTER = """\
  nginx:
    image: nginx:alpine
    container_name: c2a-nginx
    restart: unless-stopped
    ports:
      - '{port}:80'
    volumes:
      - ./generated/nginx.conf:/etc/nginx/nginx.conf:ro
    networks: [c2a-net]
    depends_on:
{depends_on}

  watchtower:
    image: {watchtower_image}
    container_name: c2a-watchtower
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    command: --label-enable --cleanup --interval 300

networks:
  c2a-net:
    driver: bridge
"""


def render_compose(accounts: list[Account]) -> str:
    services = "".join(COMPOSE_INSTANCE.format(slug=a.slug) for a in accounts)
    depends_on_lines = [f"      - chat2api-{a.slug}" for a in accounts]
    if ORCH_ENABLED:
        depends_on_lines.append("      - orchestrator")
    depends_on = "\n".join(depends_on_lines)
    body = COMPOSE_HEADER.format(image=CHAT2API_IMAGE) + services
    if ORCH_ENABLED:
        body += COMPOSE_ORCHESTRATOR.format(host_path=str(ROOT).replace("'", "''"))
    body += COMPOSE_FOOTER.format(port=NGINX_PORT, depends_on=depends_on, watchtower_image=WATCHTOWER_IMAGE)
    return body


NGINX_HEADER = """\
# 自动生成 — 由 generate.py 维护，请勿手工修改
worker_processes auto;
events { worker_connections 1024; }

http {
    server_tokens off;
    proxy_http_version 1.1;
    client_max_body_size 50m;

    # SSE / 流式响应基线
    proxy_buffering off;
    proxy_cache off;
    proxy_set_header Connection '';
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
    # Docker 内部 DNS。配合变量 proxy_pass，避免容器重建后 nginx 继续缓存旧 IP。
    resolver 127.0.0.11 ipv6=off valid=30s;

    # 简单访问日志（生产可换 json）
    log_format upstream_log '$remote_addr - [$time_local] "$request" '
                            '$status $body_bytes_sent upstream=$upstream_addr '
                            'rt=$request_time urt=$upstream_response_time';
    access_log /var/log/nginx/access.log upstream_log;

    server {
        listen 80 default_server;
        server_name _;

        location = / {
            default_type text/plain;
            return 200 "chat2api multi-instance gateway\\n";
        }

        location = /healthz {
            default_type text/plain;
            return 200 "ok\\n";
        }

"""

NGINX_ORCH_LOCATION = """\
        # ---- unified OpenAI-compatible API (load-balanced by orchestrator) ----
        location /v1/ {
            proxy_pass http://c2a-orchestrator:8080/v1/;
            proxy_set_header Host $http_host;
            proxy_set_header X-Forwarded-Host $http_host;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection '';
        }

        # ---- orchestrator (编排面板) ----
        location /orchestrator/ {
            proxy_pass http://c2a-orchestrator:8080/;
            proxy_set_header Host $http_host;
            proxy_set_header X-Forwarded-Host $http_host;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection 'upgrade';
        }

"""

NGINX_LOCATION = """\
        # ---- {slug} ({note}) ----
        location /{slug}/ {{
            set $chat2api_upstream c2a-{slug}:5005;
            rewrite ^/{slug}/(.*)$ /{api_prefix}/$1 break;
            proxy_pass http://$chat2api_upstream;
            # 把外部访问域名/协议传给 chat2api，避免页面里出现容器内网地址
            proxy_set_header Host $http_host;
            proxy_set_header X-Forwarded-Host $http_host;
            proxy_set_header X-Forwarded-Proto $scheme;
            # chat2api 内部硬编码 API_PREFIX 到 redirect / cookie / HTML 链接里，
            # 经 nginx 反代后必须把 /{api_prefix}/ 改回 /{slug}/，否则用户登录后跳转 404
            # 用 $scheme://$http_host 拼完整 URL（含客户端原始端口如 :60403）
            proxy_redirect ~^/{api_prefix}/(.*)$ $scheme://$http_host/{slug}/$1;
            proxy_cookie_path /{api_prefix} /{slug};
            # sub_filter 改写响应体内的硬编码链接（CSS/JS/HTML）；强制无 gzip 才能改
            proxy_set_header Accept-Encoding "";
            sub_filter "/{api_prefix}/" "/{slug}/";
            sub_filter_once off;
            sub_filter_types text/html text/css application/javascript application/json;
        }}

        # 反向兜底：chat2api 前端 JS 在运行时动态拼接 /{api_prefix}/...，
        # sub_filter 只改静态字符串改不到。用 307 让浏览器跳到 /{slug}/...
        # （而非 internal rewrite），保证浏览器按新 URL 的 cookie path 发送 admin_auth。
        # 307 保留 method/body，POST/PATCH 不会变 GET。
        location ~ ^/{api_prefix}/(.*)$ {{
            return 307 $scheme://$http_host/{slug}/$1$is_args$args;
        }}

"""

NGINX_FOOTER = """\
    }
}
"""


def render_nginx(accounts: list[Account]) -> str:
    locations = ""
    if ORCH_ENABLED:
        locations += NGINX_ORCH_LOCATION
    locations += "".join(
        NGINX_LOCATION.format(
            slug=a.slug,
            api_prefix=a.api_prefix,
            note=a.note or "-",
        )
        for a in accounts
    )
    return NGINX_HEADER + locations + NGINX_FOOTER


SECRETS_HEADER = """\
# chat2api 多实例访问凭证（自动生成）
# 字段：slug | path-base | AUTHORIZATION | ADMIN_PASSWORD | API_PREFIX | proxy
# 警告：含敏感数据，请妥善保管（已 chmod 600）

"""


def render_secrets(accounts: list[Account]) -> str:
    lines = [SECRETS_HEADER]
    for a in accounts:
        proxy = a.proxy_url or "-"
        lines.append(
            f"slug={a.slug}\n"
            f"  path        = /{a.slug}/v1/...\n"
            f"  AUTH        = {a.auth}\n"
            f"  ADMIN_PWD   = {a.admin_password}\n"
            f"  API_PREFIX  = {a.api_prefix}\n"
            f"  PROXY       = {proxy}\n"
            f"  note        = {a.note or '-'}\n\n"
        )
    return "".join(lines)


# ---------- writer ----------

def write_file(path: Path, content: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if mode is not None:
        path.chmod(mode)


def cleanup_orphan_envs(accounts: list[Account]) -> None:
    """CSV 中已删除的 slug，env 文件应该清理。data/ 故意保留以避免误删。"""
    if not ENV_DIR.exists():
        return
    keep = {a.slug for a in accounts}
    for env_file in ENV_DIR.glob("*.env"):
        if env_file.stem in {"orch"} or env_file.stem in keep:
            continue
        info(f"清理孤儿 env: {env_file.name}")
        env_file.unlink()


def ensure_orch_env() -> tuple[str, bool]:
    """orchestrator 凭证：首次自动生成登录密码、会话密钥和统一 API key。

    返回 (password, was_generated)。
    """
    if ORCH_ENV.exists():
        env = parse_env_file(ORCH_ENV)
        username = env.get("ORCH_USERNAME", "")
        pwd = env.get("ORCH_PASSWORD", "")
        secret = env.get("ORCH_SESSION_SECRET", "")
        api_key = env.get("ORCH_API_KEY", "")
        changed = False
        if not username:
            env["ORCH_USERNAME"] = "admin"
            changed = True
        if not api_key:
            env["ORCH_API_KEY"] = "sk-orch-" + pysecrets.token_hex(24)
            changed = True
        if pwd and secret:
            if changed:
                body = "# 自动生成 — orchestrator 凭证（generate.py 维护）\n"
                for key in ("ORCH_USERNAME", "ORCH_PASSWORD", "ORCH_SESSION_SECRET", "ORCH_API_KEY"):
                    if env.get(key):
                        body += f"{key}={env[key]}\n"
                write_file(ORCH_ENV, body, mode=0o600)
            return pwd, False
    username = "admin"
    pwd = gen_admin_password()
    secret = pysecrets.token_hex(32)
    api_key = "sk-orch-" + pysecrets.token_hex(24)
    body = (
        "# 自动生成 — orchestrator 凭证（generate.py 维护）\n"
        f"ORCH_USERNAME={username}\n"
        f"ORCH_PASSWORD={pwd}\n"
        f"ORCH_SESSION_SECRET={secret}\n"
        f"ORCH_API_KEY={api_key}\n"
    )
    write_file(ORCH_ENV, body, mode=0o600)
    return pwd, True


def parse_env_file(path: Path) -> dict[str, str]:
    """简易 .env 解析，仅本模块用。"""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def main() -> int:
    accounts = load_accounts()
    info(f"读到 {len(accounts)} 个账号")

    GEN_DIR.mkdir(parents=True, exist_ok=True)
    ENV_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 1. env files (per-instance)
    for a in accounts:
        write_file(ENV_DIR / f"{a.slug}.env", render_env(a), mode=0o600)
        (DATA_DIR / a.slug).mkdir(exist_ok=True)
    cleanup_orphan_envs(accounts)

    # 2. compose
    write_file(COMPOSE_FILE, render_compose(accounts))

    # 3. nginx
    write_file(NGINX_FILE, render_nginx(accounts))

    # 4. secrets
    write_file(SECRETS_FILE, render_secrets(accounts), mode=0o600)

    # 5. orchestrator 凭证（首次生成时打印）
    orch_first_pwd: str | None = None
    if ORCH_ENABLED:
        pwd, was_generated = ensure_orch_env()
        if was_generated:
            orch_first_pwd = pwd

    ok(f"compose:  {COMPOSE_FILE}")
    ok(f"nginx:    {NGINX_FILE}")
    ok(f"env dir:  {ENV_DIR}")
    ok(f"secrets:  {SECRETS_FILE}  (chmod 600)")
    ok(f"网关端口: {NGINX_PORT} (可用 CHAT2API_GATEWAY_PORT 覆盖)")
    if orch_first_pwd:
        sys.stdout.write(
            "\n"
            "============================================================\n"
            "  Orchestrator 首次访问用户名：admin\n"
            f"  Orchestrator 首次访问密码：{orch_first_pwd}\n"
            "  请立即记录！可通过 ./manage.sh orch-password 重置\n"
            "  访问入口：http://<vps>:{port}/orchestrator/\n"
            "============================================================\n"
            .format(port=NGINX_PORT)
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
