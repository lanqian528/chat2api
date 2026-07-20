import asyncio
import base64
import hashlib
import json
import random
import time
from urllib.parse import urlencode

from fastapi import HTTPException

from utils.Client import Client
from utils.Logger import logger
from utils.configs import (
    openai_auth_client_id,
    openai_auth_redirect_uri,
    openai_auth_scope,
    openai_auth_token_url,
    proxy_url_list,
)
from utils.routing import get_bound_proxy, save_routing_config
import utils.globals as globals

# 跨结构 key 迁移锁，防止多个并发刷新同时改 token_list/refresh_map/routing_config
_session_key_lock = asyncio.Lock()


def persist_refresh_map():
    with open(globals.REFRESH_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(globals.refresh_map, f, indent=4, ensure_ascii=False)


def persist_error_tokens():
    with open(globals.ERROR_TOKENS_FILE, "w", encoding="utf-8") as f:
        for token in globals.error_token_list:
            f.write(token + "\n")


def _decode_jwt_exp(jwt_token):
    """解析 JWT payload 的 'exp' 字段（秒级时间戳）；任何失败返回 0。"""
    if not jwt_token or "." not in jwt_token:
        return 0
    try:
        payload_b64 = jwt_token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("ascii")))
        return int(payload.get("exp") or 0)
    except Exception:
        return 0


def _extract_rotated_cookie(response, original_cookie):
    """从响应里取 NextAuth 滚动续期回写的新 session-token。

    支持：
      - 单片：`__Secure-next-auth.session-token=<value>`
      - 多片：`__Secure-next-auth.session-token.0=...; .1=...; .2=...`
        多片按下标排序后用 SESS_CHUNK_SEPARATOR（'|||'）拼接，与存储格式一致

    返回：
      - 新 cookie 值（已剥除 cookie 名）；与 original_cookie 相同则返回 None
      - 解析失败或服务端未续期返回 None
    """
    base_name = NEXTAUTH_COOKIE_NAME  # __Secure-next-auth.session-token
    chunks = {}  # idx -> value；-1 代表单片
    try:
        # curl_cffi 响应的 cookies 实际是 RequestsCookieJar（dict-like + .items()）
        jar = getattr(response, "cookies", None)
        if jar is not None:
            try:
                items = list(jar.items())
            except Exception:
                items = [(c.name, c.value) for c in jar]
            for name, value in items:
                if not name or not value:
                    continue
                if name == base_name:
                    chunks[-1] = value
                elif name.startswith(base_name + "."):
                    suffix = name[len(base_name) + 1:]
                    if suffix.isdigit():
                        chunks[int(suffix)] = value
    except Exception as e:
        logger.warning(f"[rotated_cookie] parse cookies failed: {e!r}")
        return None

    if not chunks:
        return None

    if -1 in chunks and len(chunks) == 1:
        new_value = chunks[-1]
    else:
        ordered = [chunks[i] for i in sorted(k for k in chunks if k >= 0)]
        if not ordered:
            return None
        new_value = SESS_CHUNK_SEPARATOR.join(ordered)

    if not new_value or new_value == original_cookie:
        return None
    return new_value


async def _migrate_session_key(old_key, new_key, new_access_token, jwt_exp, proxy_url=""):
    """cookie 滚动后，把所有以 old_key 为索引的数据迁移到 new_key 并持久化。

    覆盖：refresh_map / token_list(+ token.txt) / fp_map(+ fp_map.json)
         / routing_config.bindings & account_meta(+ routing_config.json)
         / error_token_list(+ error_token.txt)
    """
    if old_key == new_key:
        return
    async with _session_key_lock:
        now = int(time.time())

        # 1) refresh_map：复制旧条目并合并新字段，再删旧 key
        meta = dict(globals.refresh_map.get(old_key, {}))
        meta.update({
            "token": new_access_token,
            "timestamp": now,
            "last_success_at": now,
            "last_error": "",
            "last_error_at": 0,
            "fail_count": 0,
            "jwt_exp": jwt_exp,
            "last_proxy": proxy_url or meta.get("last_proxy", ""),
            "rotated_from": old_key[:24] + "...",
            "rotated_at": now,
        })
        globals.refresh_map[new_key] = meta
        globals.refresh_map.pop(old_key, None)
        persist_refresh_map()

        # 2) token_list / token.txt
        if old_key in globals.token_list:
            idx = globals.token_list.index(old_key)
            globals.token_list[idx] = new_key
            globals.persist_token_list()

        # 3) fp_map / fp_map.json
        if old_key in globals.fp_map:
            globals.fp_map[new_key] = globals.fp_map.pop(old_key)
            globals.persist_fp_map()

        # 4) routing_config bindings & account_meta
        routing_changed = False
        bindings = globals.routing_config.get("bindings", {}) if isinstance(globals.routing_config, dict) else {}
        if old_key in bindings:
            bindings[new_key] = bindings.pop(old_key)
            routing_changed = True
        account_meta = globals.routing_config.get("account_meta", {}) if isinstance(globals.routing_config, dict) else {}
        if old_key in account_meta:
            account_meta[new_key] = account_meta.pop(old_key)
            routing_changed = True
        if routing_changed:
            save_routing_config(globals.routing_config)

        # 5) error_token_list（理论上 rotation 发生时 old_key 不在 error 里，但兜底）
        if old_key in globals.error_token_list:
            globals.error_token_list[:] = [
                (new_key if t == old_key else t) for t in globals.error_token_list
            ]
            persist_error_tokens()

        logger.info(
            f"[rotation] session-token rotated: {old_key[:16]}... -> {new_key[:16]}... "
            f"(jwt_exp={jwt_exp}, +{jwt_exp - now}s)"
        )


async def rt2ac(refresh_token, force_refresh=False):
    if not force_refresh and (refresh_token in globals.refresh_map and int(time.time()) - globals.refresh_map.get(refresh_token, {}).get("timestamp", 0) < 5 * 24 * 60 * 60):
        access_token = globals.refresh_map[refresh_token]["token"]
        # logger.info(f"refresh_token -> access_token from cache")
        return access_token
    else:
        try:
            access_token = await chat_refresh(refresh_token)
            refresh_meta = globals.refresh_map.get(refresh_token, {})
            now = int(time.time())
            refresh_meta.update({
                "token": access_token,
                "timestamp": now,
                "last_success_at": now,
                "last_error": "",
                "last_error_at": 0,
                "fail_count": 0,
            })
            globals.refresh_map[refresh_token] = refresh_meta
            if refresh_token in globals.error_token_list:
                globals.error_token_list[:] = [item for item in globals.error_token_list if item != refresh_token]
                persist_error_tokens()
            persist_refresh_map()
            logger.info(f"refresh_token -> access_token with openai: {access_token}")
            return access_token
        except HTTPException as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail)


async def sess2ac(session_token, force_refresh=False):
    """Session cookie → access_token（带 NextAuth 滚动续期）。

    `session_token` 是带 'sess-' 前缀的存储形态（外部传入时已剥除 or 保留都支持）。
    缓存条件：
      1) timestamp 距今 < 8 分钟（绝对节流，避免高频请求打爆 NextAuth）
      2) 解码后的 JWT exp 距今 > 5 分钟（确保 token 真的还能用，避免拿死 token）
    任一条件不满足都强制刷新。
    """
    # 统一 key：带前缀的是存储形态，剥除后的是 cookie 真实值
    if session_token.startswith("sess-"):
        storage_key = session_token
        cookie_value = session_token[5:]
    else:
        storage_key = "sess-" + session_token
        cookie_value = session_token

    # 缓存命中：timestamp 节流 + JWT exp 真实有效性双重校验
    now = int(time.time())
    cached_meta = globals.refresh_map.get(storage_key, {})
    cached_token = cached_meta.get("token", "")
    cached_ts = int(cached_meta.get("timestamp", 0))
    cached_exp = int(cached_meta.get("jwt_exp", 0)) or _decode_jwt_exp(cached_token)
    if (not force_refresh
            and cached_token
            and now - cached_ts < 8 * 60
            and (cached_exp == 0 or cached_exp - now > 300)):
        return cached_token

    try:
        access_token, effective_key, jwt_exp = await fetch_session_access_token(cookie_value)
        # 若 fetch 内部完成了 cookie rotation，effective_key != storage_key，
        # 此时 refresh_map[effective_key] 已被 _migrate_session_key 完整填充，无需重复写
        if effective_key == storage_key:
            now = int(time.time())
            refresh_meta = globals.refresh_map.get(storage_key, {})
            refresh_meta.update({
                "token": access_token,
                "timestamp": now,
                "last_success_at": now,
                "last_error": "",
                "last_error_at": 0,
                "fail_count": 0,
                "jwt_exp": jwt_exp,
            })
            globals.refresh_map[storage_key] = refresh_meta
            if storage_key in globals.error_token_list:
                globals.error_token_list[:] = [item for item in globals.error_token_list if item != storage_key]
                persist_error_tokens()
            persist_refresh_map()
        logger.info(
            f"session_cookie -> access_token OK (key={effective_key[:12]}..., "
            f"jwt_exp_in={(jwt_exp - int(time.time())) if jwt_exp else 'n/a'}s, "
            f"rotated={'yes' if effective_key != storage_key else 'no'})"
        )
        return access_token
    except HTTPException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


async def fetch_session_access_token(session_cookie):
    """带 __Secure-next-auth.session-token cookie 访问 chatgpt.com/api/auth/session。

    支持两种 storage_key 格式：
      - 单片：sess-<cookie_value>
      - 多片（JWE 超 4KB 被 NextAuth 分片）：sess-<chunk0>|||<chunk1>|||<chunk2>

    返回响应 JSON 中的 accessToken 字段（JWT，调 chatgpt.com/backend-api 的 Bearer）。
    """
    session_id = hashlib.md5(session_cookie.encode()).hexdigest()
    storage_key = "sess-" + session_cookie
    bound_proxy = get_bound_proxy(storage_key)
    proxy_url = bound_proxy or (random.choice(proxy_url_list).replace("{}", session_id) if proxy_url_list else None)
    if proxy_url:
        proxy_url = proxy_url.replace("{}", session_id)
    refresh_meta = globals.refresh_map.get(storage_key, {})
    refresh_meta["last_proxy"] = proxy_url or ""
    globals.refresh_map[storage_key] = refresh_meta

    # 按 NextAuth 协议组装 Cookie header
    # 单片 → 一条 __Secure-next-auth.session-token=
    # 多片 → 多条 __Secure-next-auth.session-token.0=xxx; .1=yyy; ...
    cookie_header = _build_nextauth_cookie_header(session_cookie)

    client = Client(proxy=proxy_url, impersonate="chrome124")
    try:
        r = await client.get(
            "https://chatgpt.com/api/auth/session",
            headers={
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Cookie": cookie_header,
            },
            timeout=15,
        )
        raw_text = (r.text or "").strip()
        content_type = r.headers.get("content-type", "")
        logger.info(
            f"[sess2ac] key={storage_key[:12]}... status={r.status_code} "
            f"ctype={content_type} body_len={len(raw_text)} "
            f"proxy={'yes' if proxy_url else 'no'} chunks={cookie_header.count('session-token')}"
        )

        if r.status_code != 200:
            if storage_key not in globals.error_token_list and r.status_code in (401, 403):
                globals.error_token_list.append(storage_key)
                persist_error_tokens()
            raise Exception(
                f"chatgpt.com/api/auth/session status={r.status_code}: {raw_text[:200]}"
            )
        if not raw_text:
            raise Exception("chatgpt.com/api/auth/session 返回空响应；cookie 可能已失效")

        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            raise Exception(f"非 JSON 响应 ctype={content_type}: {raw_text[:200]}")

        # 未登录时 NextAuth 返回 {} 或 {"user": null}
        access_token = payload.get("accessToken") or payload.get("access_token")
        if not access_token:
            if storage_key not in globals.error_token_list:
                globals.error_token_list.append(storage_key)
                persist_error_tokens()
            raise Exception(
                f"session cookie 无效或过期（response keys={list(payload.keys())}）。"
                f"提示：NextAuth session token 可能分片，请确保同时提供 .0 和 .1（若存在）"
            )

        # NextAuth 滚动续期：尝试从响应 Set-Cookie 中提取新 session-token；
        # 若拿到，立刻把所有数据结构里的旧 key 替换为新 key 并持久化，达成"永不过期"
        jwt_exp = _decode_jwt_exp(access_token)
        effective_storage_key = storage_key
        try:
            rotated = _extract_rotated_cookie(r, session_cookie)
        except Exception as e:
            rotated = None
            logger.warning(f"[sess2ac] extract rotated cookie failed (non-fatal): {e!r}")
        if rotated:
            new_storage_key = "sess-" + rotated
            await _migrate_session_key(
                old_key=storage_key,
                new_key=new_storage_key,
                new_access_token=access_token,
                jwt_exp=jwt_exp,
                proxy_url=proxy_url or "",
            )
            effective_storage_key = new_storage_key
        return access_token, effective_storage_key, jwt_exp
    except Exception as e:
        now = int(time.time())
        refresh_meta = globals.refresh_map.get(storage_key, {})
        refresh_meta.update({
            "last_error": str(e)[:300],
            "last_error_at": now,
            "fail_count": int(refresh_meta.get("fail_count", 0)) + 1,
            "last_proxy": proxy_url or "",
        })
        globals.refresh_map[storage_key] = refresh_meta
        persist_refresh_map()
        logger.error(f"[sess2ac] key={storage_key[:12]}... failed: {str(e)[:400]}")
        raise HTTPException(status_code=500, detail=str(e)[:300])
    finally:
        await client.close()
        del client


# 分片分隔符（内部用，不可与 base64url 字符冲突）
SESS_CHUNK_SEPARATOR = "|||"
NEXTAUTH_COOKIE_NAME = "__Secure-next-auth.session-token"


def _build_nextauth_cookie_header(session_cookie: str) -> str:
    """根据存储的 session_cookie 字符串，构造发给 chatgpt.com 的 Cookie header。

    Args:
        session_cookie: 已去除 'sess-' 前缀的原始值。
                        - 单片：直接是 cookie value
                        - 多片：<chunk0>|||<chunk1>|||<chunk2>...

    Returns:
        Cookie header 字符串（NextAuth 规范分片格式）
    """
    if SESS_CHUNK_SEPARATOR in session_cookie:
        chunks = session_cookie.split(SESS_CHUNK_SEPARATOR)
        return "; ".join(
            f"{NEXTAUTH_COOKIE_NAME}.{i}={chunk}"
            for i, chunk in enumerate(chunks)
            if chunk.strip()
        )
    return f"{NEXTAUTH_COOKIE_NAME}={session_cookie}"


async def chat_refresh(refresh_token):
    # 使用 Codex CLI 风格：application/x-www-form-urlencoded + auth.openai.com
    # 老版 auth0.openai.com + iOS client_id 已返回 404
    form_body = urlencode({
        "grant_type": "refresh_token",
        "client_id": openai_auth_client_id,
        "refresh_token": refresh_token,
        "scope": openai_auth_scope,
    })
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Codex_CLI/0.1.0",
    }
    session_id = hashlib.md5(refresh_token.encode()).hexdigest()
    bound_proxy = get_bound_proxy(refresh_token)
    proxy_url = bound_proxy or (random.choice(proxy_url_list).replace("{}", session_id) if proxy_url_list else None)
    if proxy_url:
        proxy_url = proxy_url.replace("{}", session_id)
    refresh_meta = globals.refresh_map.get(refresh_token, {})
    refresh_meta["last_proxy"] = proxy_url or ""
    globals.refresh_map[refresh_token] = refresh_meta
    client = Client(proxy=proxy_url, impersonate=None)
    token_prefix = refresh_token[:8]
    try:
        r = await client.post(openai_auth_token_url, data=form_body, headers=headers, timeout=15)
        raw_text = (r.text or "").strip()
        content_type = r.headers.get("content-type", "")

        # 诊断日志：每次刷新都记录上游返回的关键元数据
        logger.info(
            f"[chat_refresh] token={token_prefix}... status={r.status_code} "
            f"ctype={content_type} body_len={len(raw_text)} proxy={'yes' if proxy_url else 'no'} "
            f"endpoint={openai_auth_token_url}"
        )

        # 200 路径：仍需防御解析
        if r.status_code == 200:
            if not raw_text:
                raise Exception("OpenAI returned empty body with status 200")
            try:
                payload = json.loads(raw_text)
            except json.JSONDecodeError:
                raise Exception(
                    f"OpenAI non-JSON response (status 200, ctype={content_type}): "
                    f"{raw_text[:200]}"
                )
            if "access_token" not in payload:
                raise Exception(
                    f"OpenAI JSON missing access_token: keys={list(payload.keys())} "
                    f"body={raw_text[:200]}"
                )
            return payload["access_token"]

        # 非 200 路径：详细分流并记录
        error_body_hint = raw_text[:300] if raw_text else "(empty body)"
        if "invalid_grant" in raw_text or "access_denied" in raw_text or "refresh_token_expired" in raw_text:
            if refresh_token not in globals.error_token_list:
                globals.error_token_list.append(refresh_token)
                persist_error_tokens()
            raise Exception(
                f"OpenAI rejected refresh_token (status {r.status_code}): {error_body_hint}"
            )
        raise Exception(
            f"OpenAI refresh failed (status {r.status_code}, ctype={content_type}): {error_body_hint}"
        )
    except Exception as e:
        now = int(time.time())
        refresh_meta = globals.refresh_map.get(refresh_token, {})
        refresh_meta.update({
            "last_error": str(e)[:300],
            "last_error_at": now,
            "fail_count": int(refresh_meta.get("fail_count", 0)) + 1,
            "last_proxy": proxy_url or "",
        })
        globals.refresh_map[refresh_token] = refresh_meta
        persist_refresh_map()
        logger.error(f"[chat_refresh] token={token_prefix}... failed: {str(e)[:400]}")
        raise HTTPException(status_code=500, detail=str(e)[:300])
    finally:
        await client.close()
        del client
