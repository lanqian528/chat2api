import ipaddress
import json
import time
from collections import defaultdict, deque

from fastapi import File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from app import app, templates
from utils.Client import Client
from utils.configs import admin_password, admin_ip_whitelist, admin_trust_proxy, api_prefix, authorization_list
from utils.Logger import logger
from utils.routing import (
    build_group_assignments,
    detect_token_type,
    get_dashboard_payload,
    get_routing_config,
    remove_account_binding,
    save_routing_config,
    sync_bindings_to_fp,
    update_account_meta,
    update_single_binding,
)
import utils.globals as globals
from chatgpt.refreshToken import rt2ac

ADMIN_COOKIE_NAME = "admin_auth"
ADMIN_COOKIE_MAX_AGE = 8 * 60 * 60
MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 2MB
ALLOWED_IMPORT_EXTENSIONS = {"txt", "json"}
rate_limit_buckets = defaultdict(deque)
failed_login_buckets = defaultdict(deque)

if not admin_password:
    logger.warning(
        "[admin] ADMIN_PASSWORD is NOT configured. "
        "Admin backend endpoints are disabled for safety. "
        "Set ADMIN_PASSWORD to a strong independent secret (do NOT reuse AUTHORIZATION)."
    )
elif authorization_list and admin_password in authorization_list:
    logger.warning(
        "[admin] ADMIN_PASSWORD is identical to one of AUTHORIZATION entries. "
        "Use a distinct secret to avoid privilege escalation via API key leakage."
    )


def admin_login_path():
    if api_prefix:
        return f"/{api_prefix}/admin/login"
    return "/admin/login"


def get_admin_secrets():
    """管理后台专用密码集合。

    安全要求：
      - 必须独立配置 ADMIN_PASSWORD，不再回退到 AUTHORIZATION；
      - 未配置时返回空列表 → require_admin_auth / 登录接口一律 403。
    """
    if admin_password:
        return [admin_password]
    return []


def get_client_key(request: Request):
    """获取客户端 IP。

    仅在 ADMIN_TRUST_PROXY=true 时读 X-Forwarded-For，否则用真实 TCP 连接 IP。
    避免攻击者伪造 XFF 头绕过白名单。
    """
    if admin_trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded:
            return forwarded
    if request.client:
        return request.client.host
    return "unknown"


def _is_ip_whitelisted(request: Request) -> bool:
    """检查客户端 IP 是否在白名单。空白名单 = 全放行。"""
    if not admin_ip_whitelist:
        return True
    client_ip = get_client_key(request)
    if client_ip in ("unknown", ""):
        return False
    try:
        ip_obj = ipaddress.ip_address(client_ip)
    except ValueError:
        logger.warning(f"[admin-ipwl] 无法解析客户端 IP: {client_ip}")
        return False
    for rule in admin_ip_whitelist:
        rule = rule.strip()
        if not rule:
            continue
        try:
            if "/" in rule:
                if ip_obj in ipaddress.ip_network(rule, strict=False):
                    return True
            else:
                if client_ip == rule or ip_obj == ipaddress.ip_address(rule):
                    return True
        except ValueError:
            logger.warning(f"[admin-ipwl] 白名单规则无效: {rule}")
            continue
    return False


def require_ip_whitelist(request: Request):
    """IP 白名单检查：不在白名单的直接 403，连登录页都看不到。"""
    if not _is_ip_whitelisted(request):
        client_ip = get_client_key(request)
        logger.warning(f"[admin-ipwl] 拒绝 IP: {client_ip}")
        raise HTTPException(
            status_code=403,
            detail="Forbidden: your IP is not whitelisted for admin backend",
        )


def check_rate_limit(bucket_key, limit, window_seconds):
    now = time.time()
    bucket = rate_limit_buckets[bucket_key]
    while bucket and now - bucket[0] > window_seconds:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(status_code=429, detail="Too many admin requests")
    bucket.append(now)


def record_failed_login(client_key):
    now = time.time()
    bucket = failed_login_buckets[client_key]
    while bucket and now - bucket[0] > 600:
        bucket.popleft()
    bucket.append(now)


def ensure_login_not_locked(client_key):
    now = time.time()
    bucket = failed_login_buckets[client_key]
    while bucket and now - bucket[0] > 600:
        bucket.popleft()
    if len(bucket) >= 5:
        raise HTTPException(status_code=429, detail="Too many failed login attempts")


def is_admin_authorized(request: Request):
    cookie_token = request.cookies.get(ADMIN_COOKIE_NAME, "")
    header_token = request.headers.get("authorization", "").replace("Bearer ", "").strip()
    token = header_token or cookie_token
    return bool(token and token in get_admin_secrets())


def get_current_admin_token(request: Request):
    cookie_token = request.cookies.get(ADMIN_COOKIE_NAME, "")
    header_token = request.headers.get("authorization", "").replace("Bearer ", "").strip()
    token = header_token or cookie_token
    if token and token in get_admin_secrets():
        return token
    return ""


def require_admin_auth(request: Request):
    # 第一道：IP 白名单（若开启）
    require_ip_whitelist(request)
    # 第二道：未配置 ADMIN_PASSWORD 时，后台接口一律拒绝（不再放行）
    if not get_admin_secrets():
        raise HTTPException(
            status_code=503,
            detail="Admin backend disabled: ADMIN_PASSWORD is not configured.",
        )
    check_rate_limit(f"admin:{get_client_key(request)}", 120, 60)
    if not is_admin_authorized(request):
        raise HTTPException(status_code=401, detail="Admin authorization required")


async def routing_admin_login_page(request: Request):
    require_ip_whitelist(request)
    check_rate_limit(f"admin-page:{get_client_key(request)}", 60, 60)
    if not get_admin_secrets():
        raise HTTPException(
            status_code=503,
            detail="Admin backend disabled: ADMIN_PASSWORD is not configured.",
        )
    if is_admin_authorized(request):
        return RedirectResponse(url=f"/{api_prefix}/admin/routing" if api_prefix else "/admin/routing", status_code=302)
    return templates.TemplateResponse(
        "admin_login.html",
        {
            "request": request,
            "api_prefix": api_prefix,
        },
    )


async def routing_admin_login_submit(request: Request):
    require_ip_whitelist(request)
    client_key = get_client_key(request)
    ensure_login_not_locked(client_key)
    check_rate_limit(f"admin-login:{client_key}", 10, 300)
    if not get_admin_secrets():
        raise HTTPException(
            status_code=503,
            detail="Admin backend disabled: ADMIN_PASSWORD is not configured.",
        )
    form = await request.form()
    password = (form.get("password") or "").strip()
    if not password or password not in get_admin_secrets():
        record_failed_login(client_key)
        return templates.TemplateResponse(
            "admin_login.html",
            {
                "request": request,
                "api_prefix": api_prefix,
                "error": "授权码无效",
            },
            status_code=401,
        )

    response = RedirectResponse(
        url=f"/{api_prefix}/admin/routing" if api_prefix else "/admin/routing",
        status_code=302,
    )
    failed_login_buckets.pop(client_key, None)
    # Cookie 安全：HttpOnly 阻止 JS 读取；SameSite=Strict 防 CSRF；
    # Secure 在 HTTPS 下生效（HTTP 反代内网环境 request.url.scheme 为 http，自动不发 Secure）
    is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    cookie_path = f"/{api_prefix}/admin" if api_prefix else "/admin"
    response.set_cookie(
        ADMIN_COOKIE_NAME,
        value=password,
        httponly=True,
        secure=is_https,
        samesite="strict",
        max_age=ADMIN_COOKIE_MAX_AGE,
        path=cookie_path,
    )
    return response


async def routing_admin_logout(request: Request):
    response = RedirectResponse(url=admin_login_path(), status_code=302)
    cookie_path = f"/{api_prefix}/admin" if api_prefix else "/admin"
    response.delete_cookie(ADMIN_COOKIE_NAME, path=cookie_path)
    return response


async def routing_admin_page(request: Request):
    require_ip_whitelist(request)
    check_rate_limit(f"admin-page:{get_client_key(request)}", 60, 60)
    if not get_admin_secrets():
        raise HTTPException(
            status_code=503,
            detail="Admin backend disabled: ADMIN_PASSWORD is not configured.",
        )
    if not is_admin_authorized(request):
        return RedirectResponse(url=admin_login_path(), status_code=302)
    return templates.TemplateResponse(
        "account_proxy_bindings.html",
        {
            "request": request,
            "api_prefix": api_prefix,
        },
    )


async def routing_admin_data(request: Request):
    require_admin_auth(request)
    payload = get_dashboard_payload()
    payload["routing_config"] = get_routing_config()
    payload["proxy_options"] = get_routing_config().get("proxies", [])
    return JSONResponse(payload)


async def routing_admin_save(request: Request):
    require_admin_auth(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    proxies = body.get("proxies", [])
    group_size = body.get("group_size", 25)
    if not isinstance(proxies, list):
        raise HTTPException(status_code=400, detail="proxies must be a list")
    # 允许清空代理池（直连模式）：传 [] 时清理所有 bindings
    if not proxies:
        logger.info("[admin] clearing all proxies (direct mode)")
        empty_config = {
            "proxies": [],
            "groups": [],
            "bindings": {},
            "account_meta": get_routing_config().get("account_meta", {}),
        }
        save_routing_config(empty_config)
        sync_bindings_to_fp({})
    else:
        result = build_group_assignments(list(globals.token_list), proxies, group_size)
        save_routing_config(result)
        sync_bindings_to_fp(result["bindings"])

    # 热同步 antiban 桶：不重启即生效
    try:
        from utils.antiban import bucket as _bucket
        _bucket.resync_from_routing()
    except Exception as e:  # pragma: no cover
        logger.warning(f"[admin] antiban resync failed: {e}")

    return JSONResponse(
        {
            "status": "success",
            "message": "Routing config saved" if proxies else "Proxies cleared (direct mode)",
            "summary": get_dashboard_payload()["summary"],
        }
    )


async def routing_admin_bind_account(request: Request):
    require_admin_auth(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    token = (body.get("token") or "").strip()
    proxy_url = (body.get("proxy_url") or "").strip()
    proxy_name = (body.get("proxy_name") or "").strip()
    if not token or not proxy_url:
        raise HTTPException(status_code=400, detail="token and proxy_url are required")

    config = get_routing_config()
    if not proxy_name:
        proxy = next((item for item in config.get("proxies", []) if item.get("proxy_url") == proxy_url), None)
        proxy_name = proxy.get("name") if proxy else "Custom Proxy"

    binding = update_single_binding(token, proxy_name, proxy_url)
    # 热同步 antiban 桶
    try:
        from utils.antiban import bucket as _bucket
        _bucket.resync_from_routing()
    except Exception as e:
        logger.warning(f"[admin] antiban resync failed: {e}")
    return JSONResponse({"status": "success", "binding": binding})


async def routing_admin_import_accounts(request: Request):
    require_admin_auth(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    text = (body.get("text") or "").strip()
    note = (body.get("note") or "").strip()
    group_name = (body.get("group_name") or "").strip()
    proxy_url = (body.get("proxy_url") or "").strip()
    proxy_name = (body.get("proxy_name") or "").strip()
    overwrite_existing = bool(body.get("overwrite_existing"))
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    incoming_tokens = []
    for line in text.splitlines():
        token = line.strip()
        if token and not token.startswith("#"):
            incoming_tokens.append(token)

    if not incoming_tokens:
        raise HTTPException(status_code=400, detail="No valid tokens found")

    existing = set(globals.token_list)
    added = []
    updated = []
    for token in incoming_tokens:
        if token not in existing:
            globals.token_list.append(token)
            existing.add(token)
            added.append(token)
        elif overwrite_existing:
            updated.append(token)

    if added:
        with open(globals.TOKENS_FILE, "a", encoding="utf-8") as f:
            for token in added:
                f.write(token + "\n")

    config = get_routing_config()
    if proxy_url and not proxy_name:
        proxy = next((item for item in config.get("proxies", []) if item.get("proxy_url") == proxy_url), None)
        proxy_name = proxy.get("name") if proxy else "Custom Proxy"

    for token in added + updated:
        update_account_meta(
            token,
            note=note,
            group_name=group_name or None,
            proxy_name=proxy_name or None,
            proxy_url=proxy_url or None,
        )

    return JSONResponse(
        {
            "status": "success",
            "added_count": len(added),
            "updated_count": len(updated),
            "skipped_count": len(incoming_tokens) - len(added) - len(updated),
            "message": "账号已保存",
        }
    )


async def routing_admin_parse_file(request: Request, file: UploadFile = File(...)):
    """上传文件并解析其中的 token，仅返回预览，不写入。前端确认后再调用 import 路由。"""
    require_admin_auth(request)

    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="缺少文件名")

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_IMPORT_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件后缀: .{ext}；仅允许 {sorted(ALLOWED_IMPORT_EXTENSIONS)}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大：最大 {MAX_UPLOAD_BYTES // 1024} KB",
        )

    from utils.token_parser import mask_token, parse_file
    result = parse_file(filename, content)

    # 为前端预览附加 masked 版本，避免整屏泄漏 token
    result["filename"] = filename
    result["masked"] = {
        "refresh_tokens": [mask_token(t) for t in result["refresh_tokens"]],
        "access_tokens": [mask_token(t) for t in result["access_tokens"]],
        "unknown": [mask_token(t) for t in result["unknown"]],
    }
    return JSONResponse(result)


async def routing_admin_delete_account(request: Request):
    require_admin_auth(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    token = (body.get("token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="token is required")

    if token not in globals.token_list:
        raise HTTPException(status_code=404, detail="token not found")

    globals.token_list[:] = [item for item in globals.token_list if item != token]
    with open(globals.TOKENS_FILE, "w", encoding="utf-8") as f:
        for item in globals.token_list:
            f.write(item + "\n")

    remove_account_binding(token)
    if token in globals.refresh_map:
        globals.refresh_map.pop(token, None)
        with open(globals.REFRESH_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(globals.refresh_map, f, indent=4, ensure_ascii=False)
    if token in globals.error_token_list:
        globals.error_token_list[:] = [item for item in globals.error_token_list if item != token]
        with open(globals.ERROR_TOKENS_FILE, "w", encoding="utf-8") as f:
            for item in globals.error_token_list:
                f.write(item + "\n")

    return JSONResponse(
        {
            "status": "success",
            "message": "账号已删除",
        }
    )


async def routing_admin_refresh_account(request: Request):
    require_admin_auth(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    token = (body.get("token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="token is required")
    if token not in globals.token_list:
        raise HTTPException(status_code=404, detail="token not found")
    if detect_token_type(token) != "RefreshToken":
        raise HTTPException(status_code=400, detail="Only RefreshToken supports manual refresh")

    try:
        access_token = await rt2ac(token, force_refresh=True)
    except HTTPException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    refresh_info = globals.refresh_map.get(token, {})
    return JSONResponse(
        {
            "status": "success",
            "message": "RefreshToken 刷新成功",
            "token_masked": f"{access_token[:6]}...{access_token[-4:]}" if access_token else "",
            "refresh_updated_at": refresh_info.get("last_success_at", refresh_info.get("timestamp", 0)),
        }
    )


async def routing_admin_refresh_all_accounts(request: Request):
    require_admin_auth(request)
    refresh_tokens = [token for token in globals.token_list if detect_token_type(token) == "RefreshToken"]
    if not refresh_tokens:
        return JSONResponse(
            {
                "status": "success",
                "message": "当前没有可刷新的 RefreshToken",
                "success_count": 0,
                "failed_count": 0,
            }
        )

    success_count = 0
    failed_tokens = []
    for token in refresh_tokens:
        try:
            await rt2ac(token, force_refresh=True)
            success_count += 1
        except HTTPException:
            failed_tokens.append(token)

    message = f"批量刷新完成：成功 {success_count}，失败 {len(failed_tokens)}"
    return JSONResponse(
        {
            "status": "success" if not failed_tokens else "partial",
            "message": message,
            "success_count": success_count,
            "failed_count": len(failed_tokens),
            "failed_tokens": failed_tokens,
        }
    )


async def routing_admin_test_proxy(request: Request):
    require_admin_auth(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    proxy_url = (body.get("proxy_url") or "").strip()
    if not proxy_url:
        raise HTTPException(status_code=400, detail="proxy_url is required")

    client = Client(proxy=proxy_url, timeout=15)
    results = []
    try:
        targets = [
            "https://chatgpt.com",
            "https://auth0.openai.com",
        ]
        for target in targets:
            try:
                response = await client.get(target, timeout=10)
                results.append({
                    "target": target,
                    "ok": 200 <= response.status_code < 500,
                    "status_code": response.status_code,
                })
            except Exception as exc:
                results.append({
                    "target": target,
                    "ok": False,
                    "error": str(exc),
                })

        overall_ok = all(item.get("ok") for item in results)
        return JSONResponse(
            {
                "status": "success" if overall_ok else "partial",
                "proxy_url": proxy_url,
                "results": results,
            }
        )
    finally:
        await client.close()


async def routing_admin_logs_tail(request: Request):
    """轮询日志：支持增量 since_id、级别、关键字筛选。"""
    require_admin_auth(request)

    from utils.log_buffer import log_buffer

    params = request.query_params
    since_id = params.get("since_id")
    try:
        since_id_val = int(since_id) if since_id not in (None, "") else None
    except ValueError:
        since_id_val = None

    level = (params.get("level") or "").strip().upper() or None
    keyword = (params.get("keyword") or "").strip() or None
    try:
        limit = int(params.get("limit") or 500)
    except ValueError:
        limit = 500
    limit = max(1, min(limit, 2000))

    items = log_buffer.snapshot(
        since_id=since_id_val,
        level=level,
        keyword=keyword,
        limit=limit,
    )
    return JSONResponse(
        {
            "items": items,
            "latest_id": log_buffer.latest_id,
            "capacity": log_buffer.capacity,
            "total": len(log_buffer),
        }
    )


async def routing_admin_logs_download(request: Request):
    """下载日志文本；scope=all 下载全部，否则按筛选下载当前视图。"""
    require_admin_auth(request)

    from utils.log_buffer import log_buffer, render_plaintext

    params = request.query_params
    scope = (params.get("scope") or "filtered").lower()

    if scope == "all":
        records = log_buffer.snapshot_all()
    else:
        level = (params.get("level") or "").strip().upper() or None
        keyword = (params.get("keyword") or "").strip() or None
        records = log_buffer.snapshot(level=level, keyword=keyword, limit=2000)

    text = render_plaintext(records)
    filename = f"chat2api-{int(time.time())}-{scope}.log"
    return PlainTextResponse(
        content=text,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "text/plain; charset=utf-8",
        },
    )


# ============ Harvester 账号元数据 ============

async def routing_admin_harvester_list(request: Request):
    """返回所有 Harvester 账号元数据及统计。"""
    require_admin_auth(request)
    from utils import harvester_meta
    return JSONResponse({
        "accounts": harvester_meta.list_all(),
        "stats": harvester_meta.stats(),
    })


async def routing_admin_harvester_upsert(request: Request):
    """新增或编辑账号元数据（不含密码）。"""
    require_admin_auth(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    email = (body.get("email") or "").strip()
    note = (body.get("note") or "").strip()
    proxy_name = (body.get("proxy_name") or "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="email 不合法")

    from utils import harvester_meta
    try:
        rec = harvester_meta.upsert(email, note=note, proxy_name=proxy_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse({"status": "success", "account": rec})


async def routing_admin_harvester_delete(request: Request):
    """删除元数据（不动 token.txt）。"""
    require_admin_auth(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    email = (body.get("email") or "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="email 不能为空")
    from utils import harvester_meta
    ok = harvester_meta.delete(email)
    return JSONResponse({"status": "success" if ok else "not_found"})


async def routing_admin_harvester_bulk_import(request: Request):
    """批量导入 email 清单。接受两种输入：
       1) JSON: {"rows": [{"email":"...","note":"...","proxy_name":"..."}]}
       2) multipart: file= CSV 文件（表头 email,note,proxy_name）
    """
    require_admin_auth(request)
    rows = []
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        file = form.get("file")
        if file is None:
            raise HTTPException(status_code=400, detail="缺少 file 字段")
        raw = (await file.read()).decode("utf-8", errors="replace")
        import csv
        import io
        reader = csv.DictReader(io.StringIO(raw))
        for r in reader:
            rows.append({
                "email": (r.get("email") or "").strip(),
                "note": (r.get("note") or "").strip(),
                "proxy_name": (r.get("proxy_name") or "").strip(),
            })
    else:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="需要 JSON 或 CSV 文件")
        rows = body.get("rows") or []
        if not isinstance(rows, list):
            raise HTTPException(status_code=400, detail="rows 必须是数组")

    if not rows:
        raise HTTPException(status_code=400, detail="没有可导入的行")

    from utils import harvester_meta
    result = harvester_meta.bulk_upsert(rows)
    return JSONResponse({"status": "success", **result, "total": len(rows)})


async def routing_admin_harvester_report(request: Request):
    """Harvester 采集成功/失败后回调此接口上报状态。"""
    require_admin_auth(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    email = (body.get("email") or "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="email 不能为空")
    success = bool(body.get("success", True))
    rt_prefix = (body.get("rt_prefix") or "").strip()
    error = (body.get("error") or "").strip()
    imported_token = (body.get("imported_token") or "").strip()

    from utils import harvester_meta
    rec = harvester_meta.report_harvest(
        email=email,
        rt_prefix=rt_prefix,
        success=success,
        error=error,
        imported_token=imported_token,
    )
    return JSONResponse({"status": "success", "account": rec})


# ============ Harvester 浏览器登录（OAuth PKCE，用户在本地浏览器完成）============

async def routing_admin_harvester_authorize_start(request: Request):
    """启动一次 OAuth 授权会话，返回 authorize_url 供前端展示给用户复制。"""
    require_admin_auth(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    email = (body.get("email") or "").strip()
    note = (body.get("note") or "").strip()
    proxy_name = (body.get("proxy_name") or "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="email 不合法")

    from utils import oauth_session
    try:
        result = oauth_session.start_session(email, note=note, proxy_name=proxy_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info(f"[harvester-auth] start session for {email}")
    return JSONResponse({"status": "success", **result})


async def routing_admin_harvester_authorize_exchange(request: Request):
    """用户粘贴浏览器地址栏的 com.openai.chat://...?code=X&state=Y 过来。

    步骤：
      1. pop session（验证 session_id 有效且未过期，一次性消费）
      2. 解析 callback URL 拿 code / state
      3. 校验 state 防 CSRF
      4. 用 verifier + code 调 Auth0 /oauth/token 换 refresh_token
      5. 调已有 routing_admin_import_accounts 的内部逻辑写入 chat2api 账号池
      6. 通过 harvester_meta.report_harvest 更新看板
    """
    require_admin_auth(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    session_id = (body.get("session_id") or "").strip()
    callback_url = (body.get("callback_url") or "").strip()
    if not session_id or not callback_url:
        raise HTTPException(status_code=400, detail="session_id 和 callback_url 必填")

    from urllib.parse import parse_qs, urlparse
    from utils import harvester_meta, oauth_session

    sess = oauth_session.pop_session(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="会话不存在或已过期，请重新开始")

    # 解析回调 URL
    parsed = urlparse(callback_url)
    qs = parse_qs(parsed.query)

    # error 优先
    if qs.get("error"):
        err = qs.get("error", ["unknown"])[0]
        desc = qs.get("error_description", [""])[0]
        harvester_meta.report_harvest(
            email=sess.email, success=False, error=f"{err}: {desc}"[:200]
        )
        raise HTTPException(status_code=400, detail=f"OAuth 错误: {err} {desc}")

    code_list = qs.get("code")
    state_list = qs.get("state")
    if not code_list or not state_list:
        harvester_meta.report_harvest(
            email=sess.email, success=False, error="callback URL 缺 code/state"
        )
        raise HTTPException(status_code=400, detail="回调 URL 中未找到 code 或 state")

    code = code_list[0]
    returned_state = state_list[0]
    if returned_state != sess.state:
        harvester_meta.report_harvest(
            email=sess.email, success=False, error="state mismatch (CSRF?)"
        )
        raise HTTPException(status_code=400, detail="state 不匹配，可能是 CSRF 或会话错配")

    # 换 token
    token_set = await _exchange_code_for_tokens(code, sess)
    rt = token_set.get("refresh_token", "")
    if not rt:
        harvester_meta.report_harvest(
            email=sess.email, success=False, error="Auth0 未返回 refresh_token"
        )
        raise HTTPException(status_code=502, detail="Auth0 响应缺 refresh_token")

    rt_prefix = rt[:12]

    # 复用现有的 import_accounts 业务逻辑：这里为了避免构造假 request，直接调用底层
    try:
        await _harvester_import_rt(sess, rt)
    except Exception as e:
        harvester_meta.report_harvest(
            email=sess.email, success=False, error=f"import failed: {e}"[:200]
        )
        raise HTTPException(status_code=500, detail=f"写入 chat2api 失败: {e}")

    # 更新看板
    harvester_meta.report_harvest(
        email=sess.email,
        rt_prefix=rt_prefix,
        success=True,
        imported_token=rt,
    )
    logger.info(f"[harvester-auth] ✓ {sess.email} → rt_prefix={rt_prefix[:8]}...")
    return JSONResponse({
        "status": "success",
        "email": sess.email,
        "rt_prefix": rt_prefix,
    })


async def routing_admin_harvester_import_cookie(request: Request):
    """从浏览器粘贴的 NextAuth session cookie 导入账号。

    支持 3 种粘贴格式（自动识别）：
      1. 单一 cookie value:           "eyJxxxxx..."
      2. 完整 cookie 串（多片）:      "__Secure-next-auth.session-token.0=xxx; __Secure-next-auth.session-token.1=yyy"
      3. 完整 document.cookie 字符串: "_ga=xxx; __Secure-next-auth.session-token.0=xxx; __Secure-next-auth.session-token.1=yyy; cf_clearance=xxx"

    自动提取 `__Secure-next-auth.session-token.N` 的所有片段，按顺序拼接。

    前端传递 {email, session_token, note?, proxy_name?}。
    """
    require_admin_auth(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    email = (body.get("email") or "").strip()
    raw_input = (body.get("session_token") or "").strip()
    note = (body.get("note") or "").strip()
    proxy_name = (body.get("proxy_name") or "").strip()

    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="email 不合法")
    if not raw_input:
        raise HTTPException(status_code=400, detail="session_token 不能为空")

    # ----- 智能解析分片 cookie -----
    from chatgpt.refreshToken import SESS_CHUNK_SEPARATOR, sess2ac
    session_cookie = _parse_session_cookie_input(raw_input)
    if not session_cookie or len(session_cookie) < 20:
        raise HTTPException(
            status_code=400,
            detail="未识别到有效的 session-token cookie。"
                   "请从浏览器 F12 → Application → Cookies 复制整段 Cookie 字符串粘贴。",
        )

    storage_key = "sess-" + session_cookie
    chunk_count = session_cookie.count(SESS_CHUNK_SEPARATOR) + 1 if SESS_CHUNK_SEPARATOR in session_cookie else 1
    logger.info(
        f"[harvester-cookie] parsed {chunk_count} chunk(s) for {email}"
    )

    # 验证 cookie 是否真能换出 access_token
    from utils import harvester_meta
    from utils.routing import get_routing_config, update_account_meta

    try:
        access_token = await sess2ac(storage_key, force_refresh=True)
    except Exception as e:
        harvester_meta.report_harvest(
            email=email, success=False, error=f"cookie 验证失败: {e}"
        )
        raise HTTPException(status_code=400, detail=f"Cookie 验证失败：{str(e)[:200]}")

    if not access_token:
        raise HTTPException(status_code=400, detail="Cookie 有效但未拿到 access_token")

    # 写入 token 池
    if storage_key not in globals.token_list:
        globals.token_list.append(storage_key)
        with open(globals.TOKENS_FILE, "a", encoding="utf-8") as f:
            f.write(storage_key + "\n")

    # 绑定代理 / 备注
    proxy_url = ""
    if proxy_name:
        cfg = get_routing_config()
        match = next(
            (p for p in cfg.get("proxies", []) if p.get("name") == proxy_name),
            None,
        )
        if match:
            proxy_url = match.get("proxy_url", "") or ""
        else:
            logger.warning(
                f"[harvester-cookie] proxy_name='{proxy_name}' 未找到"
            )
    final_note = f"{email} [chunks={chunk_count}]" + (f" · {note}" if note else "")
    update_account_meta(
        storage_key,
        note=final_note,
        group_name=None,
        proxy_name=proxy_name if proxy_url else None,
        proxy_url=proxy_url if proxy_url else None,
    )

    # 更新看板
    harvester_meta.report_harvest(
        email=email,
        rt_prefix=f"sess({chunk_count})...",
        success=True,
        imported_token=storage_key,
    )

    logger.info(f"[harvester-cookie] ✓ {email} → chunks={chunk_count}, access_token 已换出")
    return JSONResponse({
        "status": "success",
        "email": email,
        "token_type": "SessionToken",
        "chunks": chunk_count,
        "access_token_preview": access_token[:16] + "...",
    })


def _parse_session_cookie_input(raw: str) -> str:
    """从用户粘贴的原始输入中提取 NextAuth session-token，按分片顺序拼接。

    支持 5 种粘贴姿势：
      1. 整段 document.cookie      "_ga=x; __Secure-next-auth.session-token.0=v0; __Secure-next-auth.session-token.1=v1; ..."
      2. 只带 session 的 cookie 串 "__Secure-next-auth.session-token.0=v0; __Secure-next-auth.session-token.1=v1"
      3. 单片（老版）               "__Secure-next-auth.session-token=value"
      4. 裸 value 分号拼接（F12 Application 逐个复制后拼）  "value0;value1"
      5. 单个裸 value（未分片时）   "eyJxxx.yyy.zzz..."

    返回内部存储用的字符串：
      - 单片：cookie 原值
      - 多片：chunk0|||chunk1|||chunk2...
    """
    import re
    from chatgpt.refreshToken import SESS_CHUNK_SEPARATOR

    txt = raw.strip()
    # 去掉 "Cookie:" 前缀
    if txt.lower().startswith("cookie:"):
        txt = txt[7:].strip()

    # 归一化全角标点（用户可能用输入法不小心敲成全角）
    txt = txt.translate(str.maketrans({
        "\uff1b": ";",   # ； 全角分号
        "\uff1d": "=",   # ＝ 全角等号
        "\u3000": " ",   # 　 全角空格
        "\uff1a": ":",   # ： 全角冒号
    }))

    # 情况 1：整段只是一个裸值（无 ; 无 =）
    if "=" not in txt and ";" not in txt:
        return txt

    indexed_chunks = {}       # {.N 下标: value}（带 name.N）
    single_match = None        # 带 name 的单片
    positional_chunks = []     # 没 name 的裸 value（按顺序收集）

    for part in re.split(r";\s*", txt):
        part = part.strip()
        if not part:
            continue

        if "=" not in part:
            # 没 name 的裸 value：只接受看起来像 JWE/base64url 的长片段
            # 避免把 cookie 噪音碎片误吞
            if len(part) >= 50 and re.match(r"^[A-Za-z0-9_\-\.=+/]+$", part):
                positional_chunks.append(part)
            continue

        key, _, value = part.partition("=")
        key = key.strip()
        value = value.strip()
        # 带下标的 __Secure-next-auth.session-token.N
        m = re.match(r"^__Secure-next-auth\.session-token\.(\d+)$", key)
        if m:
            indexed_chunks[int(m.group(1))] = value
            continue
        # 不带下标的单片（老版或非分片情况）
        if key in ("__Secure-next-auth.session-token",
                   "__Host-next-auth.session-token",
                   "next-auth.session-token"):
            single_match = value

    # 优先级：带 name 的下标 chunk > 带 name 的单片 > 裸 value 顺序拼接 > 整段兜底

    if indexed_chunks:
        ordered = [indexed_chunks[i] for i in sorted(indexed_chunks.keys())]
        if len(ordered) == 1:
            return ordered[0]
        return SESS_CHUNK_SEPARATOR.join(ordered)

    if single_match:
        return single_match

    # 姿势 4：裸 value 用分号拼接的情况
    if positional_chunks:
        if len(positional_chunks) == 1:
            return positional_chunks[0]
        return SESS_CHUNK_SEPARATOR.join(positional_chunks)

    # 兜底：整段看起来是合法 JWE（长，字符集对）
    if len(txt) >= 100 and re.match(r"^[A-Za-z0-9_\-\.=+/]+$", txt):
        return txt

    return ""


async def _exchange_code_for_tokens(code: str, sess) -> dict:
    """调用 OpenAI /oauth/token 换 refresh_token。

    使用 Codex CLI 风格：application/x-www-form-urlencoded。
    端点从 oauth_session._get_oauth_config() 取（auth.openai.com/oauth/token）。
    """
    from urllib.parse import urlencode
    from utils.Client import Client
    from utils import oauth_session as _oauth

    client_id, redirect_uri, _audience, _scope, _auth_url, token_url = _oauth._get_oauth_config()
    form = urlencode({
        "grant_type": "authorization_code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code": code,
        "code_verifier": sess.verifier,
    })
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Codex_CLI/0.1.0",
    }

    c = Client(impersonate=None)
    try:
        # curl_cffi 的 post 接受 data= 作为 form body
        r = await c.post(token_url, data=form, headers=headers, timeout=20)
        raw = (r.text or "").strip()
        if r.status_code != 200:
            raise RuntimeError(f"OpenAI token status={r.status_code} body={raw[:300]}")
        import json as _json
        payload = _json.loads(raw)
        if "refresh_token" not in payload:
            raise RuntimeError(f"响应缺 refresh_token: keys={list(payload.keys())}")
        return payload
    finally:
        await c.close()


async def _harvester_import_rt(sess, refresh_token: str) -> None:
    """把 rt 写入 chat2api 账号池（复用现有 import 流程的底层调用）。"""
    from utils.routing import (
        get_routing_config,
        update_account_meta,
    )
    # 加到 globals.token_list + token.txt
    if refresh_token not in globals.token_list:
        globals.token_list.append(refresh_token)
        with open(globals.TOKENS_FILE, "a", encoding="utf-8") as f:
            f.write(refresh_token + "\n")

    # 绑定代理 / 备注
    proxy_url = ""
    proxy_name = sess.proxy_name or ""
    if proxy_name:
        cfg = get_routing_config()
        match = next(
            (p for p in cfg.get("proxies", []) if p.get("name") == proxy_name),
            None,
        )
        if match:
            proxy_url = match.get("proxy_url", "") or ""
        else:
            logger.warning(
                f"[harvester-auth] proxy_name='{proxy_name}' 未找到，rt 已导入但不绑定代理"
            )
    note = f"{sess.email}" + (f" · {sess.note}" if sess.note else "")
    update_account_meta(
        refresh_token,
        note=note,
        group_name=None,
        proxy_name=proxy_name if proxy_url else None,
        proxy_url=proxy_url if proxy_url else None,
    )


app.add_api_route("/admin/routing", routing_admin_page, methods=["GET"], response_class=HTMLResponse)
app.add_api_route("/admin/routing/data", routing_admin_data, methods=["GET"])
app.add_api_route("/admin/routing/save", routing_admin_save, methods=["POST"])
app.add_api_route("/admin/login", routing_admin_login_page, methods=["GET"], response_class=HTMLResponse)
app.add_api_route("/admin/login", routing_admin_login_submit, methods=["POST"])
app.add_api_route("/admin/logout", routing_admin_logout, methods=["POST"])
app.add_api_route("/admin/routing/account-bind", routing_admin_bind_account, methods=["POST"])
app.add_api_route("/admin/routing/accounts/import", routing_admin_import_accounts, methods=["POST"])
app.add_api_route("/admin/routing/accounts/parse-file", routing_admin_parse_file, methods=["POST"])
app.add_api_route("/admin/routing/accounts/delete", routing_admin_delete_account, methods=["POST"])
app.add_api_route("/admin/routing/accounts/refresh", routing_admin_refresh_account, methods=["POST"])
app.add_api_route("/admin/routing/accounts/refresh-all", routing_admin_refresh_all_accounts, methods=["POST"])
app.add_api_route("/admin/routing/test-proxy", routing_admin_test_proxy, methods=["POST"])
app.add_api_route("/admin/logs/tail", routing_admin_logs_tail, methods=["GET"])
app.add_api_route("/admin/logs/download", routing_admin_logs_download, methods=["GET"])
app.add_api_route("/admin/harvester/accounts", routing_admin_harvester_list, methods=["GET"])
app.add_api_route("/admin/harvester/accounts", routing_admin_harvester_upsert, methods=["POST"])
app.add_api_route("/admin/harvester/accounts/delete", routing_admin_harvester_delete, methods=["POST"])
app.add_api_route("/admin/harvester/accounts/bulk-import", routing_admin_harvester_bulk_import, methods=["POST"])
app.add_api_route("/admin/harvester/report", routing_admin_harvester_report, methods=["POST"])
app.add_api_route("/admin/harvester/authorize/start", routing_admin_harvester_authorize_start, methods=["POST"])
app.add_api_route("/admin/harvester/authorize/exchange", routing_admin_harvester_authorize_exchange, methods=["POST"])
app.add_api_route("/admin/harvester/import-cookie", routing_admin_harvester_import_cookie, methods=["POST"])

if api_prefix:
    app.add_api_route(f"/{api_prefix}/admin/routing", routing_admin_page, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route(f"/{api_prefix}/admin/routing/data", routing_admin_data, methods=["GET"])
    app.add_api_route(f"/{api_prefix}/admin/routing/save", routing_admin_save, methods=["POST"])
    app.add_api_route(f"/{api_prefix}/admin/login", routing_admin_login_page, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route(f"/{api_prefix}/admin/login", routing_admin_login_submit, methods=["POST"])
    app.add_api_route(f"/{api_prefix}/admin/logout", routing_admin_logout, methods=["POST"])
    app.add_api_route(f"/{api_prefix}/admin/routing/account-bind", routing_admin_bind_account, methods=["POST"])
    app.add_api_route(f"/{api_prefix}/admin/routing/accounts/import", routing_admin_import_accounts, methods=["POST"])
    app.add_api_route(f"/{api_prefix}/admin/routing/accounts/parse-file", routing_admin_parse_file, methods=["POST"])
    app.add_api_route(f"/{api_prefix}/admin/routing/accounts/delete", routing_admin_delete_account, methods=["POST"])
    app.add_api_route(f"/{api_prefix}/admin/routing/accounts/refresh", routing_admin_refresh_account, methods=["POST"])
    app.add_api_route(f"/{api_prefix}/admin/routing/accounts/refresh-all", routing_admin_refresh_all_accounts, methods=["POST"])
    app.add_api_route(f"/{api_prefix}/admin/routing/test-proxy", routing_admin_test_proxy, methods=["POST"])
    app.add_api_route(f"/{api_prefix}/admin/logs/tail", routing_admin_logs_tail, methods=["GET"])
    app.add_api_route(f"/{api_prefix}/admin/logs/download", routing_admin_logs_download, methods=["GET"])
    app.add_api_route(f"/{api_prefix}/admin/harvester/accounts", routing_admin_harvester_list, methods=["GET"])
    app.add_api_route(f"/{api_prefix}/admin/harvester/accounts", routing_admin_harvester_upsert, methods=["POST"])
    app.add_api_route(f"/{api_prefix}/admin/harvester/accounts/delete", routing_admin_harvester_delete, methods=["POST"])
    app.add_api_route(f"/{api_prefix}/admin/harvester/accounts/bulk-import", routing_admin_harvester_bulk_import, methods=["POST"])
    app.add_api_route(f"/{api_prefix}/admin/harvester/report", routing_admin_harvester_report, methods=["POST"])
    app.add_api_route(f"/{api_prefix}/admin/harvester/authorize/start", routing_admin_harvester_authorize_start, methods=["POST"])
    app.add_api_route(f"/{api_prefix}/admin/harvester/authorize/exchange", routing_admin_harvester_authorize_exchange, methods=["POST"])
    app.add_api_route(f"/{api_prefix}/admin/harvester/import-cookie", routing_admin_harvester_import_cookie, methods=["POST"])
