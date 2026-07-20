"""chat2api 多实例编排面板 (Orchestrator)

职责：
- 单密码登录（HMAC 签名 cookie + CSRF 双 cookie）
- 增删改账号实例（写 accounts.csv → 调 generate.py → docker compose up）
- 启停重启单实例
- 状态仪表盘（docker inspect + exit IP 抽样 + cookie age）
- 操作审计（jsonl 追加写）

所有 docker 调用走容器内 docker-cli + 挂入的 /var/run/docker.sock。
所有 compose 操作必须 --project-directory $MULTI_HOST_PATH 让 daemon 用宿主路径解析 volumes。
"""
from __future__ import annotations

import base64
import csv
import functools
import hashlib
import io
import json
import logging
import os
import re
import secrets as pysecrets
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field, field_validator
from starlette.background import BackgroundTask

# ---------- 配置 ----------

# WORK 目录策略：让容器内 WORK 路径 = 宿主 deploy/multi 绝对路径，
# 因为 docker compose 客户端（在容器内）发命令前会先解析 env_file 并检查存在性，
# 必须用容器内能访问的路径；而 daemon（在宿主）解析 volumes 用宿主路径。
# 通过 compose volume `${MULTI_HOST_PATH}:${MULTI_HOST_PATH}` 让两者重合。
HOST_PATH = (os.environ.get("MULTI_HOST_PATH") or "/work").rstrip("/")
WORK = Path(HOST_PATH)
COMPOSE_FILE_C = WORK / "generated" / "docker-compose.yml"
ACCOUNTS_CSV = WORK / "accounts.csv"
SECRETS_FILE = WORK / "generated" / "secrets.txt"
ORCH_ENV = WORK / "generated" / "orch.env"
DATA_DIR = WORK / "data"
AUDIT_FILE = WORK / "audit.jsonl"
USAGE_FILE = WORK / "usage.jsonl"

USERNAME = (os.environ.get("ORCH_USERNAME") or "admin").strip() or "admin"
PASSWORD = (os.environ.get("ORCH_PASSWORD") or "").strip()
SESSION_SECRET = (os.environ.get("ORCH_SESSION_SECRET") or "").strip()
SESSION_MAX_AGE = 8 * 3600  # 8h
SESSION_COOKIE = "orch_session"
CSRF_COOKIE = "orch_csrf"
UNIFIED_API_KEY_ENV = "ORCH_API_KEY"

if not PASSWORD or not SESSION_SECRET:
    raise RuntimeError(
        "ORCH_PASSWORD 与 ORCH_SESSION_SECRET 必须在 generated/orch.env 中设置"
    )

SLUG_RE = re.compile(r"^[a-z0-9-]{1,16}$")
PROXY_RE = re.compile(r"^(socks5|socks5h|http|https)://[^\s]+$")
ORCH_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{3,64}$")

LOG_LEVEL = os.environ.get("ORCH_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("orchestrator")

serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="orch-session-v1")

app = FastAPI(title="chat2api Orchestrator", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory="templates")
APP_DIR = Path(__file__).parent
STATIC_DIR = APP_DIR / "static"


@functools.lru_cache(maxsize=1)
def static_version() -> str:
    """根据前端资源内容生成版本号，避免部署后浏览器继续使用旧 JS/CSS。"""
    digest = hashlib.sha256()
    for name in ("static/app.js", "static/styles.css", "static/models_by_plan.json"):
        try:
            digest.update((APP_DIR / name).read_bytes())
        except FileNotFoundError:
            digest.update(name.encode("utf-8"))
    return digest.hexdigest()[:12]


@app.middleware("http")
async def no_cache_orchestrator_ui(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/static/", "/orchestrator/static/")) or request.url.path in {"/", "/orchestrator/"}:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ---------- 工具：subprocess + docker ----------

class DockerError(Exception):
    pass


def run(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
    """同步执行命令，返回 (rc, stdout, stderr)。绝不抛 stderr 给前端原文（避免泄漏路径）。"""
    logger.debug("run: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        raise DockerError(f"命令超时（{timeout}s）：{cmd[0]}")
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def dc(*args: str, timeout: int = 180) -> tuple[int, str, str]:
    """docker compose 包装，自动加 -f 与 --project-directory。"""
    cmd = [
        "docker", "compose",
        "-f", str(COMPOSE_FILE_C),
        "--project-directory", HOST_PATH,
        *args,
    ]
    return run(cmd, timeout=timeout)


def inspect(container: str) -> dict | None:
    rc, out, _ = run(["docker", "inspect", container], timeout=10)
    if rc != 0:
        return None
    try:
        data = json.loads(out)
        return data[0] if data else None
    except json.JSONDecodeError:
        return None


def regenerate_and_apply() -> None:
    """写 csv 后必须调用：先 generate.py，再 docker compose up -d --remove-orphans，
    再 nginx -s reload（compose 不会因 nginx.conf 改动重启 nginx）。"""
    rc, out, err = run(
        ["python3", str(WORK / "generate.py")], timeout=30
    )
    if rc != 0:
        logger.error("generate.py 失败：rc=%s out=%s err=%s", rc, out, err)
        raise DockerError(f"配置生成失败：{(err or out)[:300]}")

    rc, out, err = dc("up", "-d", "--remove-orphans", timeout=240)
    if rc != 0:
        logger.error("compose up 失败：rc=%s err=%s", rc, err)
        raise DockerError(f"docker compose 失败：{(err or out)[:300]}")

    # nginx.conf 变化必须 reload，不然新 location 不生效
    rc, out, err = run(
        ["docker", "exec", "c2a-nginx", "nginx", "-s", "reload"], timeout=10
    )
    if rc != 0:
        logger.warning("nginx reload 失败（非致命）：%s", (err or out)[:200])


# ---------- 工具：CSV / env / secrets ----------

def read_accounts() -> list[dict[str, str]]:
    if not ACCOUNTS_CSV.exists():
        return []
    out: list[dict[str, str]] = []
    with ACCOUNTS_CSV.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            slug = (row.get("slug") or "").strip()
            if not slug:
                continue
            out.append({
                "slug": slug,
                "proxy_url": (row.get("proxy_url") or "").strip(),
                "note": (row.get("note") or "").strip(),
            })
    return out


def write_accounts(rows: list[dict[str, str]]) -> None:
    """原子写：tmp + rename。csv 头固定。"""
    tmp = ACCOUNTS_CSV.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["slug", "proxy_url", "note"])
        writer.writeheader()
        for r in rows:
            writer.writerow({
                "slug": r["slug"],
                "proxy_url": r.get("proxy_url", ""),
                "note": r.get("note", ""),
            })
    tmp.replace(ACCOUNTS_CSV)


def read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def write_env_file(path: Path, values: dict[str, str]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for key, value in values.items():
            f.write(f"{key}={value}\n")
    tmp.chmod(0o600)
    tmp.replace(path)


def orch_credentials() -> dict[str, str]:
    env = read_env_file(ORCH_ENV)
    username = (env.get("ORCH_USERNAME") or USERNAME or "admin").strip() or "admin"
    password = (env.get("ORCH_PASSWORD") or PASSWORD).strip()
    secret = (env.get("ORCH_SESSION_SECRET") or SESSION_SECRET).strip()
    version = hashlib.sha256(f"{username}\0{password}".encode("utf-8")).hexdigest()[:16]
    return {
        "username": username,
        "password": password,
        "secret": secret,
        "version": version,
    }


def mask_proxy(url: str) -> str:
    """socks5://user:pass@host:port → socks5://****@host:port"""
    if not url:
        return ""
    m = re.match(r"^(\w+)://([^@/]+@)?(.+)$", url)
    if not m:
        return url
    scheme, _, host = m.groups()
    return f"{scheme}://****@{host}" if _ else f"{scheme}://{host}"


def mask_secret(s: str, head: int = 6, tail: int = 4) -> str:
    if not s:
        return ""
    if len(s) <= head + tail + 3:
        return "*" * len(s)
    return f"{s[:head]}...{s[-tail:]}"


def public_origin(request: Request) -> str:
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",", 1)[0].strip()
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or ""
    ).split(",", 1)[0].strip()
    bare_host = host
    if bare_host.startswith("[") and "]" in bare_host:
        bare_host = bare_host[1:bare_host.index("]")]
    elif ":" in bare_host:
        bare_host = bare_host.rsplit(":", 1)[0]
    if not host or bare_host in {"localhost", "127.0.0.1", "0.0.0.0"} or bare_host.startswith("c2a-"):
        return ""
    return f"{proto}://{host}"


def public_url(request: Request, path: str) -> str:
    clean_path = "/" + path.lstrip("/")
    origin = public_origin(request).rstrip("/")
    return f"{origin}{clean_path}" if origin else clean_path


def unified_api_key() -> str:
    env = read_env_file(ORCH_ENV)
    return (env.get(UNIFIED_API_KEY_ENV) or os.environ.get(UNIFIED_API_KEY_ENV) or "").strip()


def require_unified_api_key(request: Request) -> None:
    expected = unified_api_key()
    if not expected:
        raise HTTPException(status_code=503, detail="统一 API Key 未生成，请重新 ./manage.sh apply")
    auth = (request.headers.get("authorization") or "").strip()
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else auth
    if not pysecrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _extract_json_body(body: bytes, content_type: str) -> dict[str, Any]:
    if not body or "json" not in content_type.lower():
        return {}
    try:
        data = json.loads(body.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _affinity_key(request: Request, body_json: dict[str, Any]) -> str:
    for header in ("x-chat2api-affinity", "x-conversation-id", "x-request-affinity"):
        val = (request.headers.get(header) or "").strip()
        if val:
            return val
    for key in (
        "chat2api_affinity_key",
        "librechat_conversation_id",
        "conversation_id",
        "parent_conversation_id",
    ):
        val = body_json.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _candidate_models(slug: str) -> set[str]:
    try:
        info = _get_instance_info(slug)
        return {
            (m.get("id") if isinstance(m, dict) else str(m))
            for m in info.get("models", [])
            if m
        }
    except Exception:
        return set()


def _backend_candidates(model: str = "") -> list[dict[str, str]]:
    all_rows: list[dict[str, str]] = []
    matched: list[dict[str, str]] = []
    for row in read_accounts():
        slug = row["slug"]
        env = read_env_file(WORK / "generated" / "env" / f"{slug}.env")
        auth = env.get("AUTHORIZATION", "")
        prefix = env.get("API_PREFIX", "")
        if not auth or not prefix:
            continue
        item = {"slug": slug, "auth": auth, "api_prefix": prefix}
        all_rows.append(item)
        models = _candidate_models(slug) if model else set()
        if model and models and model in models:
            matched.append(item)
    return matched or all_rows


_proxy_rr_cursor = 0


def _ordered_backends(candidates: list[dict[str, str]], affinity: str) -> list[dict[str, str]]:
    global _proxy_rr_cursor
    if not candidates:
        return []
    if affinity:
        digest = hashlib.sha256(affinity.encode("utf-8")).hexdigest()
        start = int(digest, 16) % len(candidates)
    else:
        start = _proxy_rr_cursor % len(candidates)
        _proxy_rr_cursor += 1
    return candidates[start:] + candidates[:start]


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
    "authorization",
    "cookie",
}


def _client_ip(request: Request) -> str:
    xff = (request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
    return xff or (request.client.host if request.client else "?")


def _usage_from_body(data: Any) -> dict[str, int | None]:
    usage = data.get("usage") if isinstance(data, dict) else {}
    if not isinstance(usage, dict):
        usage = {}
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    total = usage.get("total_tokens")
    if prompt is None:
        prompt = usage.get("input_tokens")
    if completion is None:
        completion = usage.get("output_tokens")
    if total is None and prompt is not None and completion is not None:
        try:
            total = int(prompt) + int(completion)
        except (TypeError, ValueError):
            total = None

    def as_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    return {
        "prompt_tokens": as_int(prompt),
        "completion_tokens": as_int(completion),
        "total_tokens": as_int(total),
    }


def _write_usage(record: dict[str, Any]) -> None:
    try:
        with USAGE_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.error("usage write failed: %s", e)


def _record_usage(
    request: Request,
    *,
    slug: str,
    path: str,
    model: str,
    stream: bool,
    status_code: int,
    duration_ms: int,
    ok: bool,
    request_id: str,
    usage: dict[str, int | None] | None = None,
    error: str = "",
    stream_compat: bool = False,
) -> None:
    token_usage = usage or {}
    _write_usage({
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "request_id": request_id,
        "ip": _client_ip(request),
        "slug": slug,
        "path": path,
        "endpoint": path.rsplit("/", 1)[-1] if path else "",
        "model": model,
        "stream": stream,
        "stream_compat": stream_compat,
        "status": status_code,
        "ok": ok,
        "prompt_tokens": token_usage.get("prompt_tokens"),
        "completion_tokens": token_usage.get("completion_tokens"),
        "total_tokens": token_usage.get("total_tokens"),
        "duration_ms": duration_ms,
        "error": error[:300],
    })


def read_usage(limit: int = 200) -> list[dict[str, Any]]:
    if not USAGE_FILE.exists():
        return []
    lines = USAGE_FILE.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for line in reversed(lines[-limit * 3:]):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(out) >= limit:
            break
    return out


def usage_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    total_requests = len(records)
    success = sum(1 for r in records if r.get("ok"))
    failed = total_requests - success
    total_tokens = sum(int(r.get("total_tokens") or 0) for r in records)
    prompt_tokens = sum(int(r.get("prompt_tokens") or 0) for r in records)
    completion_tokens = sum(int(r.get("completion_tokens") or 0) for r in records)
    durations = [int(r.get("duration_ms") or 0) for r in records if r.get("duration_ms") is not None]
    avg_duration_ms = round(sum(durations) / len(durations)) if durations else 0
    sorted_durations = sorted(durations)
    p95_index = max(0, min(len(sorted_durations) - 1, int((len(sorted_durations) - 1) * 0.95))) if sorted_durations else 0
    p95_duration_ms = sorted_durations[p95_index] if sorted_durations else 0
    by_slug: dict[str, dict[str, Any]] = {}
    by_model: dict[str, int] = {}
    by_endpoint: dict[str, int] = {}
    by_hour: dict[str, dict[str, int]] = {}
    for r in records:
        slug = str(r.get("slug") or "-")
        slug_row = by_slug.setdefault(slug, {"slug": slug, "requests": 0, "tokens": 0, "errors": 0})
        slug_row["requests"] += 1
        slug_row["tokens"] += int(r.get("total_tokens") or 0)
        if not r.get("ok"):
            slug_row["errors"] += 1
        model = str(r.get("model") or "-")
        by_model[model] = by_model.get(model, 0) + 1
        endpoint = str(r.get("endpoint") or "-")
        by_endpoint[endpoint] = by_endpoint.get(endpoint, 0) + 1
        hour = str(r.get("ts") or "")[:13]
        if hour:
            hour_row = by_hour.setdefault(hour, {"requests": 0, "tokens": 0, "duration_ms": 0, "duration_count": 0})
            hour_row["requests"] += 1
            hour_row["tokens"] += int(r.get("total_tokens") or 0)
            if r.get("duration_ms") is not None:
                hour_row["duration_ms"] += int(r.get("duration_ms") or 0)
                hour_row["duration_count"] += 1
    busiest = sorted(by_slug.values(), key=lambda x: (x["requests"], x["tokens"]), reverse=True)
    return {
        "total_requests": total_requests,
        "success": success,
        "failed": failed,
        "success_rate": round(success * 100 / total_requests, 1) if total_requests else 0,
        "total_tokens": total_tokens,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "avg_duration_ms": avg_duration_ms,
        "p95_duration_ms": p95_duration_ms,
        "top_slug": busiest[0]["slug"] if busiest else "-",
        "by_slug": busiest,
        "by_model": sorted(
            [{"model": k, "requests": v} for k, v in by_model.items()],
            key=lambda x: x["requests"],
            reverse=True,
        ),
        "by_endpoint": sorted(
            [{"endpoint": k, "requests": v} for k, v in by_endpoint.items()],
            key=lambda x: x["requests"],
            reverse=True,
        ),
        "timeline": [
            {
                "hour": hour,
                "requests": row["requests"],
                "tokens": row["tokens"],
                "avg_duration_ms": round(row["duration_ms"] / row["duration_count"]) if row["duration_count"] else 0,
            }
            for hour, row in sorted(by_hour.items())
        ][-24:],
    }


async def _close_upstream(resp: httpx.Response, client: httpx.AsyncClient) -> None:
    await resp.aclose()
    await client.aclose()


async def _forward_unified_request(
    request: Request,
    backend: dict[str, str],
    path: str,
    body: bytes,
    body_json: dict[str, Any],
    model: str,
    request_id: str,
    started: float,
) -> StreamingResponse:
    upstream_path = f"/{backend['api_prefix']}/v1/{path.lstrip('/')}"
    url = f"http://c2a-{backend['slug']}:5005{upstream_path}"
    if request.url.query:
        url += f"?{request.url.query}"

    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP_HEADERS
    }
    headers["Authorization"] = f"Bearer {backend['auth']}"
    headers["X-Chat2API-Orchestrator"] = "1"
    headers["X-Chat2API-Upstream-Slug"] = backend["slug"]

    client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=15.0))
    req = client.build_request(
        request.method,
        url,
        headers=headers,
        content=body,
    )
    try:
        resp = await client.send(req, stream=True)
    except Exception:
        await client.aclose()
        raise
    duration_ms = int((time.perf_counter() - started) * 1000)

    response_headers = {
        k: v
        for k, v in resp.headers.items()
        if k.lower() not in HOP_BY_HOP_HEADERS
        and k.lower() not in {"content-length", "content-encoding"}
    }
    response_headers["X-Chat2API-Upstream-Slug"] = backend["slug"]
    content_type = resp.headers.get("content-type", "")
    is_stream = _is_truthy(body_json.get("stream")) or content_type.startswith("text/event-stream")
    if not is_stream and content_type.startswith("application/json"):
        raw = await resp.aread()
        parsed: Any = {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = {}
        _record_usage(
            request,
            slug=backend["slug"],
            path=f"/v1/{path}",
            model=model,
            stream=False,
            status_code=resp.status_code,
            duration_ms=duration_ms,
            ok=200 <= resp.status_code < 400,
            request_id=request_id,
            usage=_usage_from_body(parsed),
            error="" if 200 <= resp.status_code < 400 else str(parsed)[:300],
        )
        await resp.aclose()
        await client.aclose()
        return StreamingResponse(
            iter([raw]),
            status_code=resp.status_code,
            headers=response_headers,
            media_type=content_type or None,
        )
    _record_usage(
        request,
        slug=backend["slug"],
        path=f"/v1/{path}",
        model=model,
        stream=is_stream,
        status_code=resp.status_code,
        duration_ms=duration_ms,
        ok=200 <= resp.status_code < 400,
        request_id=request_id,
        error="" if 200 <= resp.status_code < 400 else f"HTTP {resp.status_code}",
    )
    return StreamingResponse(
        resp.aiter_raw(),
        status_code=resp.status_code,
        headers=response_headers,
        background=BackgroundTask(_close_upstream, resp, client),
    )


def _openai_sse_chunk(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _as_openai_stream_events(data: dict[str, Any], model: str) -> list[str]:
    created = int(data.get("created") or time.time())
    chat_id = str(data.get("id") or f"chatcmpl-orch-{pysecrets.token_hex(12)}")
    model_id = str(data.get("model") or model or "unknown")
    choice = ((data.get("choices") or [{}])[0] or {})
    message = choice.get("message") or {}
    content = message.get("content")
    if content is None:
        content = data.get("output_text", "")
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    finish_reason = choice.get("finish_reason") or data.get("finish_reason") or "stop"

    base = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model_id,
    }
    first = {
        **base,
        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
    }
    delta = {
        **base,
        "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
    }
    final = {
        **base,
        "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
    }
    return [_openai_sse_chunk(first), _openai_sse_chunk(delta), _openai_sse_chunk(final), "data: [DONE]\n\n"]


async def _forward_unified_stream_compat(
    request: Request,
    backend: dict[str, str],
    path: str,
    body_json: dict[str, Any],
    model: str,
    request_id: str,
    started: float,
) -> StreamingResponse:
    compat_body = {**body_json, "stream": False}
    upstream_path = f"/{backend['api_prefix']}/v1/{path.lstrip('/')}"
    url = f"http://c2a-{backend['slug']}:5005{upstream_path}"
    if request.url.query:
        url += f"?{request.url.query}"

    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP_HEADERS
    }
    headers["Authorization"] = f"Bearer {backend['auth']}"
    headers["Content-Type"] = "application/json"
    headers["X-Chat2API-Orchestrator"] = "1"
    headers["X-Chat2API-Upstream-Slug"] = backend["slug"]
    content = json.dumps(compat_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=15.0)) as client:
        resp = await client.post(url, headers=headers, content=content)
        resp.raise_for_status()
        data = resp.json()
    duration_ms = int((time.perf_counter() - started) * 1000)
    _record_usage(
        request,
        slug=backend["slug"],
        path=f"/v1/{path}",
        model=model,
        stream=True,
        status_code=resp.status_code,
        duration_ms=duration_ms,
        ok=True,
        request_id=request_id,
        usage=_usage_from_body(data),
        stream_compat=True,
    )

    async def event_generator():
        for event in _as_openai_stream_events(data, model):
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Chat2API-Upstream-Slug": backend["slug"],
            "X-Chat2API-Stream-Compat": "1",
        },
    )


# ---------- 出口 IP 缓存 ----------

_exit_ip_cache: dict[str, tuple[str, float]] = {}
EXIT_IP_TTL = 60.0


def get_exit_ip(slug: str, force: bool = False) -> str | None:
    now = time.time()
    if not force and slug in _exit_ip_cache:
        ip, ts = _exit_ip_cache[slug]
        if now - ts < EXIT_IP_TTL:
            return ip
    rc, out, _ = run(
        ["docker", "exec", f"c2a-{slug}", "curl", "-s", "--max-time", "6",
         "https://api.ipify.org"],
        timeout=10,
    )
    ip = out.strip() if rc == 0 and out.strip() else None
    if ip:
        _exit_ip_cache[slug] = (ip, now)
    return ip


def get_cookie_last_success(slug: str) -> int | None:
    """读 data/{slug}/refresh_map.json，返回最新 last_success_at（unix ts）。"""
    p = DATA_DIR / slug / "refresh_map.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        ts_list = [
            int(v.get("last_success_at") or v.get("timestamp") or 0)
            for v in data.values()
            if isinstance(v, dict)
        ]
        ts_list = [t for t in ts_list if t > 0]
        return max(ts_list) if ts_list else None
    except Exception:
        return None


# ---------- 审计 ----------

def audit(action: str, request: Request, ok: bool, **fields: Any) -> None:
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "actor": "admin",
        "ip": request.client.host if request.client else "?",
        "action": action,
        "ok": ok,
        **fields,
    }
    try:
        with AUDIT_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.error("audit write failed: %s", e)


def read_audit(limit: int = 200) -> list[dict]:
    if not AUDIT_FILE.exists():
        return []
    lines = AUDIT_FILE.read_text(encoding="utf-8").splitlines()
    out: list[dict] = []
    for line in reversed(lines[-limit * 2:]):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(out) >= limit:
            break
    return out


def redact_log_text(text: str) -> str:
    """日志对前端展示前做基础脱敏，避免误复制密钥。"""
    patterns = [
        (r"(Bearer\s+)[A-Za-z0-9._=-]{20,}", r"\1***"),
        (r"(AUTHORIZATION=)[^\s]+", r"\1***"),
        (r"(sk-[A-Za-z0-9_-]{8})[A-Za-z0-9_-]+", r"\1***"),
        (r"(sess-)[^\s\"']{24,}", r"\1***"),
        (r"(rt_[^\s\"']{8})[^\s\"']+", r"\1***"),
        (r"(eyJ[A-Za-z0-9_-]{16})[A-Za-z0-9._-]+", r"\1***"),
    ]
    for pattern, repl in patterns:
        text = re.sub(pattern, repl, text)
    return text


def log_targets() -> list[dict[str, str]]:
    targets = [
        {"id": "orchestrator", "label": "orchestrator 面板", "container": "c2a-orchestrator"},
        {"id": "nginx", "label": "nginx 网关", "container": "c2a-nginx"},
        {"id": "watchtower", "label": "watchtower 更新器", "container": "c2a-watchtower"},
    ]
    for row in read_accounts():
        slug = row["slug"]
        targets.append({"id": slug, "label": f"实例 {slug}", "container": f"c2a-{slug}"})
    return targets


def read_container_logs(container: str, tail: int = 80) -> tuple[bool, str]:
    rc, out, err = run(
        ["docker", "logs", "--tail", str(tail), "--timestamps", container],
        timeout=20,
    )
    raw = "\n".join(part for part in (out, err) if part.strip())
    if rc != 0 and not raw:
        raw = f"docker logs failed: rc={rc}"
    return rc == 0, redact_log_text(raw or "(无日志输出)")


# ---------- 鉴权 ----------

def issue_session_token(username: str, version: str) -> str:
    return serializer.dumps({"u": username, "v": version})


def verify_session_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        data = serializer.loads(token, max_age=SESSION_MAX_AGE)
        creds = orch_credentials()
        return (
            isinstance(data, dict)
            and data.get("u") == creds["username"]
            and data.get("v") == creds["version"]
        )
    except (BadSignature, SignatureExpired):
        return False


def gen_csrf() -> str:
    return pysecrets.token_hex(16)


def require_session(
    request: Request,
    orch_session: str | None = Cookie(default=None),
) -> None:
    if not verify_session_token(orch_session):
        raise HTTPException(status_code=401, detail="未登录")


def require_csrf(request: Request) -> None:
    """双 cookie 模式：cookie orch_csrf 必须等于 header X-CSRF-Token。"""
    cookie_val = request.cookies.get(CSRF_COOKIE) or ""
    header_val = request.headers.get("x-csrf-token") or ""
    if not cookie_val or not pysecrets.compare_digest(cookie_val, header_val):
        raise HTTPException(status_code=403, detail="CSRF 校验失败")


# 登录速率限制（同 IP 60s 内最多 5 次失败）
_login_attempts: dict[str, list[float]] = {}


def check_login_rate(ip: str) -> bool:
    now = time.time()
    bucket = _login_attempts.setdefault(ip, [])
    bucket[:] = [t for t in bucket if now - t < 60]
    return len(bucket) < 5


def record_login_failure(ip: str) -> None:
    _login_attempts.setdefault(ip, []).append(time.time())


# ---------- 路由：基础 ----------

@app.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"ok": True})


@app.get("/v1/models")
async def unified_models(request: Request) -> JSONResponse:
    require_unified_api_key(request)
    model_ids: set[str] = set()
    for row in read_accounts():
        model_ids.update(_candidate_models(row["slug"]))
    data = [
        {
            "id": mid,
            "object": "model",
            "created": 0,
            "owned_by": "chat2api-orchestrator",
        }
        for mid in sorted(model_ids)
    ]
    audit("unified_models", request, True, model_count=len(data))
    return JSONResponse({"object": "list", "data": data})


@app.api_route(
    "/v1/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def unified_proxy(path: str, request: Request) -> Response:
    require_unified_api_key(request)
    body = await request.body()
    body_json = _extract_json_body(body, request.headers.get("content-type", ""))
    model = str(body_json.get("model") or "").strip()
    affinity = _affinity_key(request, body_json)
    candidates = _backend_candidates(model)
    if not candidates:
        raise HTTPException(status_code=503, detail="暂无可用实例，请先在编排面板新增账号")

    last_error = ""
    stream_compat = path.lstrip("/") == "chat/completions" and _is_truthy(body_json.get("stream"))
    for backend in _ordered_backends(candidates, affinity):
        request_id = request.headers.get("x-request-id") or f"orch-{int(time.time() * 1000)}-{pysecrets.token_hex(4)}"
        started = time.perf_counter()
        try:
            if stream_compat:
                resp = await _forward_unified_stream_compat(request, backend, path, body_json, model, request_id, started)
            else:
                resp = await _forward_unified_request(request, backend, path, body, body_json, model, request_id, started)
            audit(
                "unified_proxy",
                request,
                True,
                slug=backend["slug"],
                path=f"/v1/{path}",
                model=model or "",
                affinity=bool(affinity),
                stream_compat=stream_compat,
            )
            return resp
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            last_error = str(e)[:200]
            status_code = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else 502
            _record_usage(
                request,
                slug=backend["slug"],
                path=f"/v1/{path}",
                model=model or "",
                stream=_is_truthy(body_json.get("stream")),
                status_code=status_code,
                duration_ms=int((time.perf_counter() - started) * 1000),
                ok=False,
                request_id=request_id,
                error=last_error,
                stream_compat=stream_compat,
            )
            audit(
                "unified_proxy",
                request,
                False,
                slug=backend["slug"],
                path=f"/v1/{path}",
                model=model or "",
                error=last_error,
            )
            continue
    raise HTTPException(status_code=502, detail=f"所有实例转发失败：{last_error}")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": None}
    )


@app.post("/login")
async def login(
    request: Request,
    response: Response,
    username: str = Form("admin"),
    password: str = Form(...),
) -> Response:
    ip = request.client.host if request.client else "?"
    if not check_login_rate(ip):
        audit("login", request, False, reason="rate_limited")
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "尝试过多，请稍候再试"},
            status_code=429,
        )
    creds = orch_credentials()
    if (
        not pysecrets.compare_digest(username.strip(), creds["username"])
        or not pysecrets.compare_digest(password, creds["password"])
    ):
        record_login_failure(ip)
        audit("login", request, False, reason="bad_credentials", username=username[:80])
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "用户名或密码错误", "username": username},
            status_code=401,
        )

    token = issue_session_token(creds["username"], creds["version"])
    csrf = gen_csrf()
    is_https = request.url.scheme == "https" or \
        request.headers.get("x-forwarded-proto") == "https"
    resp = RedirectResponse(url="./", status_code=303)
    resp.set_cookie(
        SESSION_COOKIE, token,
        max_age=SESSION_MAX_AGE,
        httponly=True, samesite="strict", secure=is_https, path="/",
    )
    resp.set_cookie(
        CSRF_COOKIE, csrf,
        max_age=SESSION_MAX_AGE,
        httponly=False, samesite="strict", secure=is_https, path="/",
    )
    audit("login", request, True, username=creds["username"])
    return resp


@app.post("/logout")
async def logout(request: Request, _: None = Depends(require_session)) -> Response:
    audit("logout", request, True)
    resp = RedirectResponse(url="./login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    resp.delete_cookie(CSRF_COOKIE, path="/")
    return resp


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    orch_session: str | None = Cookie(default=None),
) -> Response:
    if not verify_session_token(orch_session):
        return RedirectResponse(url="./login", status_code=303)
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "static_version": static_version()},
    )


# ---------- API: accounts CRUD ----------

class AccountIn(BaseModel):
    slug: str
    proxy_url: str = ""
    note: str = ""

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        v = v.strip()
        if not SLUG_RE.match(v):
            raise ValueError("slug 不合法（需 [a-z0-9-]{1,16}）")
        return v

    @field_validator("proxy_url")
    @classmethod
    def _proxy(cls, v: str) -> str:
        v = v.strip()
        if v and not PROXY_RE.match(v):
            raise ValueError("proxy_url 必须以 socks5/socks5h/http/https:// 开头")
        return v


class AccountPatch(BaseModel):
    proxy_url: str | None = None
    note: str | None = None

    @field_validator("proxy_url")
    @classmethod
    def _proxy(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if v and not PROXY_RE.match(v):
            raise ValueError("proxy_url 必须以 socks5/socks5h/http/https:// 开头")
        return v


class OrchestratorCredentialPatch(BaseModel):
    username: str
    current_password: str
    new_password: str

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        v = v.strip()
        if not ORCH_USERNAME_RE.match(v):
            raise ValueError("用户名需 3-64 位，仅支持字母、数字、_.@-")
        return v

    @field_validator("current_password")
    @classmethod
    def _current_password(cls, v: str) -> str:
        if not v or "\n" in v or "\r" in v:
            raise ValueError("当前密码必填")
        return v

    @field_validator("new_password")
    @classmethod
    def _new_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("新密码至少 8 位")
        if "\n" in v or "\r" in v:
            raise ValueError("新密码不能包含换行")
        return v


@app.get("/api/orchestrator/account", dependencies=[Depends(require_session)])
async def api_orchestrator_account() -> JSONResponse:
    creds = orch_credentials()
    return JSONResponse({"username": creds["username"]})


@app.get("/api/unified", dependencies=[Depends(require_session), Depends(require_csrf)])
async def api_unified_credentials(request: Request) -> JSONResponse:
    key = unified_api_key()
    if not key:
        raise HTTPException(status_code=503, detail="统一 API Key 未生成，请重新 ./manage.sh apply")
    base_path = "/v1"
    chat_path = "/v1/chat/completions"
    responses_path = "/v1/responses"
    compact_path = "/v1/responses/compact"
    audit("reveal_unified_api", request, True)
    return JSONResponse({
        "base_path": base_path,
        "chat_completions_path": chat_path,
        "responses_path": responses_path,
        "responses_compact_path": compact_path,
        "base_url": public_url(request, base_path),
        "chat_completions_url": public_url(request, chat_path),
        "responses_url": public_url(request, responses_path),
        "responses_compact_url": public_url(request, compact_path),
        "api_key": key,
        "strategy": "支持 /v1/chat/completions、/v1/responses、/v1/responses/compact；无会话键时轮询，有会话键时固定到同一容器",
    })


@app.patch(
    "/api/orchestrator/account",
    dependencies=[Depends(require_session), Depends(require_csrf)],
)
async def api_update_orchestrator_account(
    payload: OrchestratorCredentialPatch,
    request: Request,
) -> JSONResponse:
    creds = orch_credentials()
    if not pysecrets.compare_digest(payload.current_password, creds["password"]):
        audit("update_orchestrator_account", request, False, reason="bad_current_password")
        raise HTTPException(status_code=403, detail="当前密码错误")

    env = read_env_file(ORCH_ENV)
    env["ORCH_USERNAME"] = payload.username
    env["ORCH_PASSWORD"] = payload.new_password
    env["ORCH_SESSION_SECRET"] = env.get("ORCH_SESSION_SECRET") or creds["secret"]
    write_env_file(ORCH_ENV, env)
    audit("update_orchestrator_account", request, True, username=payload.username)
    return JSONResponse({"ok": True, "username": payload.username, "relogin": True})


@app.get("/api/accounts", dependencies=[Depends(require_session)])
async def api_list_accounts() -> JSONResponse:
    rows = read_accounts()
    out = []
    for r in rows:
        slug_env = read_env_file(WORK / "generated" / "env" / f"{r['slug']}.env")
        out.append({
            "slug": r["slug"],
            "proxy_url_masked": mask_proxy(r["proxy_url"]),
            "has_proxy": bool(r["proxy_url"]),
            "note": r["note"],
            "auth_masked": mask_secret(slug_env.get("AUTHORIZATION", "")),
            "admin_pwd_masked": mask_secret(slug_env.get("ADMIN_PASSWORD", "")),
            "api_prefix": slug_env.get("API_PREFIX", ""),
        })
    return JSONResponse({"accounts": out})


@app.post(
    "/api/accounts",
    dependencies=[Depends(require_session), Depends(require_csrf)],
)
async def api_add_account(payload: AccountIn, request: Request) -> JSONResponse:
    rows = read_accounts()
    if any(r["slug"] == payload.slug for r in rows):
        raise HTTPException(status_code=409, detail=f"slug={payload.slug} 已存在")
    rows.append(payload.model_dump())
    write_accounts(rows)
    try:
        regenerate_and_apply()
    except DockerError as e:
        # 回滚 csv
        write_accounts([r for r in rows if r["slug"] != payload.slug])
        audit("add_account", request, False, slug=payload.slug, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    audit("add_account", request, True, slug=payload.slug)
    return JSONResponse({"ok": True, "slug": payload.slug})


@app.patch(
    "/api/accounts/{slug}",
    dependencies=[Depends(require_session), Depends(require_csrf)],
)
async def api_patch_account(
    slug: str, payload: AccountPatch, request: Request
) -> JSONResponse:
    if not SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="slug 不合法")
    rows = read_accounts()
    target = next((r for r in rows if r["slug"] == slug), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"slug={slug} 不存在")
    if payload.proxy_url is not None:
        target["proxy_url"] = payload.proxy_url
    if payload.note is not None:
        target["note"] = payload.note
    write_accounts(rows)
    try:
        regenerate_and_apply()
    except DockerError as e:
        audit("patch_account", request, False, slug=slug, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    audit("patch_account", request, True, slug=slug, fields=payload.model_dump(exclude_none=True))
    return JSONResponse({"ok": True, "slug": slug})


@app.delete(
    "/api/accounts/{slug}",
    dependencies=[Depends(require_session), Depends(require_csrf)],
)
async def api_delete_account(slug: str, request: Request) -> JSONResponse:
    if not SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="slug 不合法")
    rows = read_accounts()
    if not any(r["slug"] == slug for r in rows):
        raise HTTPException(status_code=404, detail=f"slug={slug} 不存在")
    write_accounts([r for r in rows if r["slug"] != slug])
    try:
        regenerate_and_apply()
    except DockerError as e:
        audit("delete_account", request, False, slug=slug, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    audit("delete_account", request, True, slug=slug, note="data/ 目录保留")
    return JSONResponse({"ok": True, "slug": slug})


# ---------- API: 实例运维 ----------

ALLOWED_OPS = {"start", "stop", "restart"}


@app.post(
    "/api/instances/{slug}/{op}",
    dependencies=[Depends(require_session), Depends(require_csrf)],
)
async def api_instance_op(slug: str, op: str, request: Request) -> JSONResponse:
    if op == "probe-models":
        # 兼容旧版前端路径：/api/instances/{slug}/probe-models
        return await api_probe_models(slug, request)
    if op not in ALLOWED_OPS:
        raise HTTPException(status_code=400, detail=f"非法操作 {op}")
    if not SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="slug 不合法")
    if not any(r["slug"] == slug for r in read_accounts()):
        raise HTTPException(status_code=404, detail=f"slug={slug} 不存在")
    rc, out, err = dc(op, f"chat2api-{slug}", timeout=120)
    success = rc == 0
    audit(f"instance_{op}", request, success, slug=slug,
          err=(err or "")[:200] if not success else "")
    if not success:
        raise HTTPException(status_code=500, detail=(err or out)[:300])
    return JSONResponse({"ok": True, "slug": slug, "op": op})


# ---------- API: 状态 ----------

def _cached_instance_info(slug: str) -> dict:
    """带 5min 内存缓存的 info 取数。api_status 每 5s 轮询用，避免每次重算 JWT+IO。"""
    now = time.time()
    cached = _models_cache.get(slug)
    if cached and now - cached[1] < INFO_CACHE_TTL:
        return cached[0]
    info = _get_instance_info(slug)
    _models_cache[slug] = (info, now)
    return info


@app.get("/api/status", dependencies=[Depends(require_session)])
async def api_status() -> JSONResponse:
    rows = read_accounts()
    instances = []
    for r in rows:
        slug = r["slug"]
        info = inspect(f"c2a-{slug}") or {}
        state = info.get("State", {})
        health = state.get("Health", {}).get("Status") if state else None
        started_at = state.get("StartedAt") if state else None
        uptime_seconds: int | None = None
        if started_at:
            try:
                # docker 的 StartedAt 是 RFC3339 + 纳秒；切到 26 位再 fromisoformat
                ts_str = started_at.replace("Z", "+00:00")[:26] + "+00:00" \
                    if "." in started_at and "Z" in started_at else started_at.replace("Z", "+00:00")
                dt = datetime.fromisoformat(ts_str)
                uptime_seconds = int(
                    (datetime.now(timezone.utc) - dt).total_seconds()
                )
            except (ValueError, TypeError):
                uptime_seconds = None
        # 调用层信息（带 5min cache，不影响轮询性能）
        try:
            call_info = _cached_instance_info(slug)
        except Exception as e:
            logger.warning("status: get info for %s failed: %s", slug, e)
            call_info = {}
        instances.append({
            "slug": slug,
            "container": f"c2a-{slug}",
            "state": state.get("Status") if state else "absent",
            "health": health or "n/a",
            "started_at": started_at,
            "uptime_seconds": uptime_seconds,
            "proxy_masked": mask_proxy(r["proxy_url"]),
            "has_proxy": bool(r["proxy_url"]),
            "exit_ip": _exit_ip_cache.get(slug, (None, 0))[0],
            "cookie_last_success_at": get_cookie_last_success(slug),
            "note": r["note"],
            # 新增：调用层（不含 AUTHORIZATION 原文）
            "plan_type": call_info.get("plan_type", "unknown"),
            "plan_label": call_info.get("plan_label", "未知"),
            "plan_color": call_info.get("plan_color", "rose"),
            "models": [m.get("id") for m in (call_info.get("models") or []) if isinstance(m, dict) and m.get("id")],
        })
    return JSONResponse({
        "instances": instances,
        "server_time": int(time.time()),
    })


@app.get(
    "/api/instances/{slug}/exit-ip",
    dependencies=[Depends(require_session)],
)
async def api_exit_ip(slug: str, force: int = Query(0)) -> JSONResponse:
    if not SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="slug 不合法")
    ip = get_exit_ip(slug, force=bool(force))
    return JSONResponse({"slug": slug, "exit_ip": ip or ""})


# ---------- API: 凭证查看（敏感） ----------

@app.get(
    "/api/secrets/{slug}",
    dependencies=[Depends(require_session), Depends(require_csrf)],
)
async def api_reveal_secret(slug: str, request: Request) -> JSONResponse:
    if not SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="slug 不合法")
    env = read_env_file(WORK / "generated" / "env" / f"{slug}.env")
    if not env:
        audit("reveal_secret", request, False, slug=slug, reason="not_found")
        raise HTTPException(status_code=404, detail=f"slug={slug} 凭证不存在")
    audit("reveal_secret", request, True, slug=slug)
    return JSONResponse({
        "slug": slug,
        "AUTHORIZATION": env.get("AUTHORIZATION", ""),
        "ADMIN_PASSWORD": env.get("ADMIN_PASSWORD", ""),
        "API_PREFIX": env.get("API_PREFIX", ""),
        "PROXY_URL": env.get("PROXY_URL", ""),
    })


# ---------- API: 审计 ----------

@app.get("/api/audit", dependencies=[Depends(require_session)])
async def api_audit(limit: int = Query(200, ge=1, le=2000)) -> JSONResponse:
    return JSONResponse({"records": read_audit(limit)})


@app.get(
    "/api/usage",
    dependencies=[Depends(require_session), Depends(require_csrf)],
)
async def api_usage(limit: int = Query(500, ge=1, le=5000)) -> JSONResponse:
    records = read_usage(limit)
    return JSONResponse({"summary": usage_summary(records), "records": records})


@app.get(
    "/api/log-targets",
    dependencies=[Depends(require_session), Depends(require_csrf)],
)
async def api_log_targets() -> JSONResponse:
    return JSONResponse({"targets": log_targets()})


@app.get(
    "/api/logs",
    dependencies=[Depends(require_session), Depends(require_csrf)],
)
async def api_logs(
    request: Request,
    target: str = Query("orchestrator"),
    tail: int = Query(200, ge=20, le=2000),
) -> JSONResponse:
    target_map = {item["id"]: item for item in log_targets()}
    item = target_map.get(target)
    if not item:
        audit("view_logs", request, False, target=target, reason="invalid_target")
        raise HTTPException(status_code=400, detail="日志目标不存在")

    container = item["container"]
    ok, text = read_container_logs(container, tail=tail)
    audit("view_logs", request, ok, target=target, tail=tail)
    if not ok:
        return JSONResponse(
            {
                "ok": False,
                "target": target,
                "container": container,
                "tail": tail,
                "logs": text,
            },
            status_code=200,
        )
    return JSONResponse({
        "ok": True,
        "target": target,
        "container": container,
        "tail": tail,
        "logs": text,
    })


# ====================================================================
# 调用层信息聚合 (info / probe / playground / export)
# ====================================================================

MODELS_BY_PLAN_FILE = Path(__file__).parent / "static" / "models_by_plan.json"
DEEP_RESEARCH_MODEL_ALIASES = (
    "o3-deep-research",
    "o4-mini-deep-research",
    "gpt-4o-deep-research",
    "deep-research",
)
DEEP_RESEARCH_CAPABLE_PREFIXES = (
    "gpt-4",
    "gpt-4o",
    "gpt-5",
    "o1",
    "o3",
    "o4",
)
_models_cache: dict[str, tuple[dict, float]] = {}  # slug -> (info_dict, ts)
INFO_CACHE_TTL = 300.0  # 5 分钟
PROBE_MIN_INTERVAL = 30.0  # 单 slug 探测最小间隔
_probe_last: dict[str, float] = {}


@functools.lru_cache(maxsize=1)
def _load_static_models() -> dict:
    """读 static/models_by_plan.json；启动后只读一次（除非进程重启）。"""
    try:
        return json.loads(MODELS_BY_PLAN_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error("加载 models_by_plan.json 失败：%s", e)
        return {"plans": {"unknown": {"label": "未知", "color": "rose", "models": []}}}


def _is_deep_research_capable(model_id: str) -> bool:
    if not model_id or model_id in DEEP_RESEARCH_MODEL_ALIASES:
        return False
    return model_id.startswith(DEEP_RESEARCH_CAPABLE_PREFIXES)


def _probe_model_entries(model_ids: list[str]) -> list[dict[str, str]]:
    ids = {str(model_id) for model_id in (model_ids or []) if model_id}
    if any(_is_deep_research_capable(model_id) for model_id in ids):
        ids.update(DEEP_RESEARCH_MODEL_ALIASES)
    return [
        {
            "id": model_id,
            "source": "alias" if model_id in DEEP_RESEARCH_MODEL_ALIASES else "probe",
        }
        for model_id in sorted(ids)
    ]


def _parse_jwt_plan(access_token: str) -> str:
    """从 OpenAI access_token JWT 的 payload 取 chatgpt_plan_type。

    JWT 结构: header.payload.signature。payload 是 base64url 编码的 JSON，
    里面 https://api.openai.com/auth.chatgpt_plan_type = "free"/"plus"/"team"/"pro"。
    任何失败返回 "unknown"。
    """
    if not access_token or "." not in access_token:
        return "unknown"
    try:
        payload_b64 = access_token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("ascii")))
        auth_claims = payload.get("https://api.openai.com/auth") or {}
        plan = (auth_claims.get("chatgpt_plan_type") or "").strip().lower()
        return plan or "unknown"
    except Exception:
        return "unknown"


def _read_latest_access_token(slug: str) -> str:
    """读 data/{slug}/refresh_map.json，返回 last_success_at 最新那条的 token 字段。"""
    p = DATA_DIR / slug / "refresh_map.json"
    if not p.exists():
        return ""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return ""
        latest: tuple[int, str] = (0, "")
        for v in data.values():
            if not isinstance(v, dict):
                continue
            ts = int(v.get("last_success_at") or v.get("timestamp") or 0)
            tok = v.get("token") or ""
            if ts > latest[0] and tok:
                latest = (ts, tok)
        return latest[1]
    except Exception:
        return ""


def _get_instance_info(slug: str) -> dict:
    """汇总实例的调用层信息（不含 AUTHORIZATION 原文，仅 masked）。"""
    env = read_env_file(WORK / "generated" / "env" / f"{slug}.env")
    api_prefix = env.get("API_PREFIX", "")
    authorization = env.get("AUTHORIZATION", "")
    # gateway 暴露在容器外端口 60403，nginx 反代到 c2a-{slug}:5005
    # 这里给"对外可调用"的 URL；调用方自己拼 /v1
    gateway_port = os.environ.get("ORCH_GATEWAY_PUBLIC_PORT", "60403")
    gateway_host = os.environ.get("ORCH_GATEWAY_PUBLIC_HOST", "")
    if gateway_host:
        base_url = f"http://{gateway_host}:{gateway_port}/{api_prefix}/v1" if api_prefix else ""
    else:
        # 没配公开 host 就给相对路径，浏览器拼当前 origin
        base_url = f"/{api_prefix}/v1" if api_prefix else ""

    access_token = _read_latest_access_token(slug)
    plan_type = _parse_jwt_plan(access_token) if access_token else "unknown"
    static = _load_static_models()
    plan_entry = static.get("plans", {}).get(plan_type) or static.get("plans", {}).get("unknown", {})
    models = [{"id": m, "source": "plan"} for m in plan_entry.get("models", [])]

    return {
        "slug": slug,
        "base_url": base_url,
        "api_prefix": api_prefix,
        "authorization": authorization,  # 内部端点返回原文，前端展示前 mask
        "auth_masked": mask_secret(authorization, head=6, tail=4),
        "plan_type": plan_type,
        "plan_label": plan_entry.get("label", "未知"),
        "plan_color": plan_entry.get("color", "rose"),
        "plan_source": "jwt" if access_token else "default",
        "models": models,
        "generated_at": int(time.time()),
    }


@app.get(
    "/api/instances/{slug}/info",
    dependencies=[Depends(require_session)],
)
async def api_instance_info(slug: str) -> JSONResponse:
    """单实例调用层信息（5min 缓存）。AUTHORIZATION 不下发，仅 masked。"""
    if not SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="slug 不合法")
    if not any(r["slug"] == slug for r in read_accounts()):
        raise HTTPException(status_code=404, detail=f"slug={slug} 不存在")

    now = time.time()
    cached = _models_cache.get(slug)
    info = _cached_instance_info(slug)

    # 出口前再次剥离 AUTHORIZATION 原文，浏览器只见 masked
    safe = {k: v for k, v in info.items() if k != "authorization"}
    safe["cached"] = bool(cached and now - cached[1] < INFO_CACHE_TTL)
    return JSONResponse(safe)


async def _probe_models(slug: str, api_prefix: str, auth: str) -> list[dict[str, str]]:
    """容器内网 GET c2a-{slug}:5005/{api_prefix}/v1/models，返回模型展示条目。

    chat2api 的 /v1/models 是 OpenAI 兼容协议，返回 {"object":"list","data":[{"id":"...",...}]}。
    深度研究是 chat2api 支持的调用别名，上游模型列表不一定直接返回，所以这里补充展示。
    认证用 AUTHORIZATION 作 Bearer token。
    """
    url = f"http://c2a-{slug}:5005/{api_prefix}/v1/models" if api_prefix else f"http://c2a-{slug}:5005/v1/models"
    headers = {"Authorization": f"Bearer {auth}"} if auth else {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        model_ids = [str(it.get("id")) for it in items if isinstance(it, dict) and it.get("id")]
        return _probe_model_entries(model_ids)


@app.post(
    "/api/probe-models/{slug}",
    dependencies=[Depends(require_session), Depends(require_csrf)],
)
async def api_probe_models(slug: str, request: Request) -> JSONResponse:
    """强制调实例 /v1/models 取真实可用模型；单 slug 30s 限频；写审计。"""
    if not SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="slug 不合法")
    if not any(r["slug"] == slug for r in read_accounts()):
        raise HTTPException(status_code=404, detail=f"slug={slug} 不存在")

    now = time.time()
    last = _probe_last.get(slug, 0)
    if now - last < PROBE_MIN_INTERVAL:
        wait = int(PROBE_MIN_INTERVAL - (now - last))
        audit("probe_models", request, False, slug=slug, reason="rate_limited", wait_s=wait)
        raise HTTPException(status_code=429, detail=f"探测过快，请 {wait}s 后再试")
    _probe_last[slug] = now

    env = read_env_file(WORK / "generated" / "env" / f"{slug}.env")
    if not env:
        audit("probe_models", request, False, slug=slug, reason="env_missing")
        raise HTTPException(status_code=404, detail=f"slug={slug} env 不存在")

    try:
        model_entries = await _probe_models(slug, env.get("API_PREFIX", ""), env.get("AUTHORIZATION", ""))
    except httpx.HTTPStatusError as e:
        _, logs = read_container_logs(f"c2a-{slug}", tail=80)
        audit("probe_models", request, False, slug=slug, http_status=e.response.status_code)
        raise HTTPException(
            status_code=502,
            detail=(
                f"实例返回 {e.response.status_code}: {e.response.text[:300]}\n\n"
                f"--- c2a-{slug} 最近日志 ---\n{logs[-6000:]}"
            ),
        )
    except Exception as e:
        _, logs = read_container_logs(f"c2a-{slug}", tail=80)
        audit("probe_models", request, False, slug=slug, error=str(e)[:200])
        raise HTTPException(
            status_code=500,
            detail=f"探测失败：{str(e)[:300]}\n\n--- c2a-{slug} 最近日志 ---\n{logs[-6000:]}",
        )

    # 把 probe 结果合入 cache（增量），保留 plan_type 等信息
    cached = _models_cache.get(slug)
    base = cached[0] if cached else _get_instance_info(slug)
    model_ids = [m["id"] for m in model_entries]
    base = {**base, "models": model_entries, "probed_at": int(now)}
    _models_cache[slug] = (base, now)

    audit("probe_models", request, True, slug=slug, model_count=len(model_ids))
    return JSONResponse({
        "slug": slug,
        "models": model_ids,
        "model_entries": model_entries,
        "probed_at": int(now),
    })


# ---------- 调用汇总 & 导出 ----------

def _build_aggregate() -> list[dict]:
    """同步聚合所有实例的 info（含 AUTHORIZATION 原文，供导出使用）。"""
    rows = []
    for r in read_accounts():
        slug = r["slug"]
        # 强制取实时 info（含原文 auth），不走 _models_cache（cache 已剥离 auth）
        info = _get_instance_info(slug)
        # 附带容器状态供前端着色
        cont = inspect(f"c2a-{slug}") or {}
        state = cont.get("State", {})
        info["container_state"] = state.get("Status") if state else "absent"
        info["container_health"] = (state.get("Health", {}) or {}).get("Status") or "n/a"
        rows.append(info)
    return rows


def _strip_auth(rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in r.items() if k != "authorization"} for r in rows]


@app.get(
    "/api/instances/aggregate",
    dependencies=[Depends(require_session)],
)
async def api_aggregate() -> JSONResponse:
    """全实例聚合（不下发 AUTHORIZATION 原文）。"""
    rows = _build_aggregate()
    return JSONResponse({"instances": _strip_auth(rows), "server_time": int(time.time())})


def _gen_litellm_yaml(rows: list[dict], gateway_origin: str) -> str:
    """生成 LiteLLM proxy 兼容的 config.yaml。

    每个 (slug × model) 组合一条 model_list 条目；model_name 用 `{slug}-{model}` 命名以便区分。
    """
    lines = [
        "# 由 chat2api Orchestrator 自动生成",
        f"# 生成时间: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "model_list:",
    ]
    for r in rows:
        slug = r["slug"]
        prefix = r.get("api_prefix", "")
        base = f"{gateway_origin}/{prefix}/v1" if prefix else r.get("base_url", "")
        auth = r.get("authorization", "")
        for m in r.get("models", []):
            mid = m.get("id") if isinstance(m, dict) else str(m)
            if not mid:
                continue
            lines.extend([
                f"  - model_name: {slug}-{mid}",
                f"    litellm_params:",
                f"      model: openai/{mid}",
                f"      api_base: {base}",
                f"      api_key: {auth}",
            ])
    return "\n".join(lines) + "\n"


def _gen_oneapi_json(rows: list[dict], gateway_origin: str) -> str:
    """生成 OneAPI / new-api 兼容的渠道导入 JSON 数组。"""
    channels = []
    for r in rows:
        prefix = r.get("api_prefix", "")
        base = f"{gateway_origin}/{prefix}" if prefix else gateway_origin
        models = [m.get("id") for m in r.get("models", []) if isinstance(m, dict) and m.get("id")]
        channels.append({
            "name": f"chat2api-{r['slug']}",
            "type": 1,  # OpenAI
            "base_url": base,
            "key": r.get("authorization", ""),
            "models": ",".join(models),
            "group": r.get("plan_type", "default"),
            "status": 1,
        })
    return json.dumps(channels, indent=2, ensure_ascii=False) + "\n"


def _gen_librechat_yaml(rows: list[dict], gateway_origin: str) -> str:
    """生成 LibreChat endpoints.custom 片段。"""
    lines = [
        "# 由 chat2api Orchestrator 自动生成 — 复制 endpoints.custom 部分到你的 librechat.yaml",
        f"# 生成时间: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "endpoints:",
        "  custom:",
    ]
    for r in rows:
        prefix = r.get("api_prefix", "")
        base = f"{gateway_origin}/{prefix}/v1" if prefix else r.get("base_url", "")
        auth = r.get("authorization", "")
        models = [m.get("id") for m in r.get("models", []) if isinstance(m, dict) and m.get("id")]
        models_csv = ", ".join(f'"{m}"' for m in models) or '"gpt-5-5"'
        lines.extend([
            f"    - name: \"chat2api-{r['slug']}\"",
            f"      apiKey: \"{auth}\"",
            f"      baseURL: \"{base}\"",
            f"      models:",
            f"        default: [{models_csv}]",
            f"        fetch: false",
            f"      titleConvo: true",
            f"      titleModel: \"current_model\"",
            f"      modelDisplayLabel: \"chat2api-{r['slug']} ({r.get('plan_label', '?')})\"",
        ])
    return "\n".join(lines) + "\n"


_EXPORT_FORMATS = {
    "litellm":   ("litellm-config.yaml",   "application/x-yaml",  _gen_litellm_yaml),
    "oneapi":    ("oneapi-channels.json",  "application/json",     _gen_oneapi_json),
    "librechat": ("librechat-endpoints.yaml","application/x-yaml", _gen_librechat_yaml),
}


@app.get(
    "/api/export/{fmt}",
    dependencies=[Depends(require_session)],
)
async def api_export(fmt: str, request: Request) -> Response:
    """导出多上游配置到三种主流网关 / 客户端格式。包含 AUTHORIZATION 原文。

    安全：仅 session 鉴权（无 CSRF, 因为 GET 触发下载），写审计。
    """
    if fmt not in _EXPORT_FORMATS:
        raise HTTPException(status_code=400, detail=f"不支持的格式: {fmt}")
    filename, mime, generator = _EXPORT_FORMATS[fmt]
    # 拼对外可访问的 origin（导出文件里需要全 URL）
    gateway_port = os.environ.get("ORCH_GATEWAY_PUBLIC_PORT", "60403")
    gateway_host = os.environ.get("ORCH_GATEWAY_PUBLIC_HOST") or request.url.hostname or "localhost"
    gateway_origin = f"http://{gateway_host}:{gateway_port}"
    rows = _build_aggregate()
    body = generator(rows, gateway_origin)
    audit("export_config", request, True, fmt=fmt, instance_count=len(rows))
    return Response(
        content=body,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------- Playground ----------

PG_PER_SLUG_LIMIT = 6      # 每分钟
PG_GLOBAL_LIMIT = 30       # 每分钟
PG_WINDOW = 60.0           # 1 分钟滑动
PG_MAX_TOKENS_HARD = 4096
PG_TIMEOUT_CONNECT = 5.0
PG_TIMEOUT_READ = 30.0
_pg_attempts: dict[str, list[float]] = {}
_pg_global_attempts: list[float] = []


def _pg_rate_limit_check(slug: str) -> tuple[bool, str]:
    """滑动窗口限流。返回 (ok, reason)。"""
    now = time.time()
    cutoff = now - PG_WINDOW
    # 全局
    _pg_global_attempts[:] = [t for t in _pg_global_attempts if t > cutoff]
    if len(_pg_global_attempts) >= PG_GLOBAL_LIMIT:
        return False, f"全局限流（{PG_GLOBAL_LIMIT}/min 已满）"
    # 单 slug
    lst = _pg_attempts.setdefault(slug, [])
    lst[:] = [t for t in lst if t > cutoff]
    if len(lst) >= PG_PER_SLUG_LIMIT:
        return False, f"slug={slug} 限流（{PG_PER_SLUG_LIMIT}/min 已满）"
    lst.append(now)
    _pg_global_attempts.append(now)
    return True, ""


@app.get(
    "/api/playground/options",
    dependencies=[Depends(require_session)],
)
async def api_playground_options() -> JSONResponse:
    """返回所有实例 + 它们当前可用模型，供前端下拉框联动。"""
    instances = []
    for r in read_accounts():
        slug = r["slug"]
        cached = _models_cache.get(slug)
        info = cached[0] if cached else _get_instance_info(slug)
        instances.append({
            "slug": slug,
            "plan_type": info.get("plan_type", "unknown"),
            "plan_label": info.get("plan_label", "未知"),
            "models": [m.get("id") for m in info.get("models", []) if isinstance(m, dict) and m.get("id")],
        })
    return JSONResponse({"instances": instances})


@app.post(
    "/api/playground/invoke",
    dependencies=[Depends(require_session), Depends(require_csrf)],
)
async def api_playground_invoke(request: Request) -> JSONResponse:
    """服务端代发 chat completions（不流式 MVP）。"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")
    slug = (body.get("slug") or "").strip()
    model = (body.get("model") or "").strip()
    system_prompt = body.get("system") or ""
    user_prompt = body.get("user") or ""
    temperature = body.get("temperature")
    max_tokens = body.get("max_tokens")

    if not SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="slug 不合法")
    if not any(r["slug"] == slug for r in read_accounts()):
        raise HTTPException(status_code=404, detail=f"slug={slug} 不存在")
    if not model:
        raise HTTPException(status_code=400, detail="model 必填")
    if not user_prompt:
        raise HTTPException(status_code=400, detail="user prompt 不能为空")

    # 参数夹紧
    try:
        temperature = float(temperature) if temperature is not None else 0.7
    except (TypeError, ValueError):
        temperature = 0.7
    temperature = max(0.0, min(2.0, temperature))
    try:
        max_tokens = int(max_tokens) if max_tokens is not None else 512
    except (TypeError, ValueError):
        max_tokens = 512
    max_tokens = max(1, min(PG_MAX_TOKENS_HARD, max_tokens))

    # 限流
    ok, reason = _pg_rate_limit_check(slug)
    if not ok:
        audit("playground_invoke", request, False, slug=slug, model=model, reason="rate_limited")
        raise HTTPException(status_code=429, detail=reason)

    env = read_env_file(WORK / "generated" / "env" / f"{slug}.env")
    if not env:
        raise HTTPException(status_code=404, detail=f"slug={slug} env 不存在")
    api_prefix = env.get("API_PREFIX", "")
    auth = env.get("AUTHORIZATION", "")

    url = f"http://c2a-{slug}:5005/{api_prefix}/v1/chat/completions" if api_prefix else f"http://c2a-{slug}:5005/v1/chat/completions"
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth}",
    }

    t0 = time.time()
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(PG_TIMEOUT_READ, connect=PG_TIMEOUT_CONNECT),
        ) as client:
            r = await client.post(url, json=payload, headers=headers)
        latency_ms = int((time.time() - t0) * 1000)
        data: Any = None
        try:
            data = r.json()
        except Exception:
            data = None
        if r.status_code != 200:
            audit("playground_invoke", request, False, slug=slug, model=model,
                  http_status=r.status_code, latency_ms=latency_ms,
                  prompt_chars=len(user_prompt) + len(system_prompt))
            return JSONResponse({
                "ok": False,
                "status": r.status_code,
                "latency_ms": latency_ms,
                "error": (data.get("error") if isinstance(data, dict) else None) or r.text[:300],
            })
        content = ""
        usage = {}
        if isinstance(data, dict):
            choices = data.get("choices") or []
            if choices and isinstance(choices[0], dict):
                msg = choices[0].get("message") or {}
                content = msg.get("content") or ""
            usage = data.get("usage") or {}
        audit("playground_invoke", request, True, slug=slug, model=model,
              latency_ms=latency_ms,
              prompt_chars=len(user_prompt) + len(system_prompt),
              completion_chars=len(content),
              prompt_tokens=usage.get("prompt_tokens"),
              completion_tokens=usage.get("completion_tokens"))
        return JSONResponse({
            "ok": True,
            "status": 200,
            "latency_ms": latency_ms,
            "content": content,
            "usage": usage,
        })
    except httpx.TimeoutException:
        latency_ms = int((time.time() - t0) * 1000)
        audit("playground_invoke", request, False, slug=slug, model=model,
              reason="timeout", latency_ms=latency_ms)
        return JSONResponse({"ok": False, "latency_ms": latency_ms,
                             "error": f"超时（>{int(PG_TIMEOUT_READ)}s）"}, status_code=200)
    except Exception as e:
        latency_ms = int((time.time() - t0) * 1000)
        audit("playground_invoke", request, False, slug=slug, model=model,
              reason="exception", error=str(e)[:200], latency_ms=latency_ms)
        return JSONResponse({"ok": False, "latency_ms": latency_ms,
                             "error": str(e)[:300]}, status_code=200)
