"""iOS ChatGPT app 的 OAuth2 PKCE 流程。"""

import asyncio
import base64
import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .models import Account, HarvestResult, TokenSet
from .totp import current_code as totp_code


logger = logging.getLogger("harvester")

# 成功回调类型：拿到 TokenSet 后立即调用，rt 完整值只在这里短暂出现
OnSuccessCallback = Callable[[Account, TokenSet], Awaitable[None]]


# ========================= PKCE =========================

def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_pkce_pair() -> tuple:
    """RFC 7636 PKCE pair。返回 (verifier, challenge)。"""
    verifier = _base64url(secrets.token_bytes(32))
    challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def verify_challenge(verifier: str, challenge: str) -> bool:
    return hmac.compare_digest(
        _base64url(hashlib.sha256(verifier.encode("ascii")).digest()),
        challenge,
    )


def generate_state() -> str:
    return _base64url(secrets.token_bytes(16))


# ========================= Authorize URL =========================

AUTH_BASE = "https://auth0.openai.com/authorize"
TOKEN_ENDPOINT = "https://auth0.openai.com/oauth/token"


def build_authorize_url(challenge: str, state: str, config) -> str:
    params = {
        "client_id": config.oauth_client_id,
        "audience": config.oauth_audience,
        "redirect_uri": config.oauth_redirect_uri,
        "response_type": "code",
        "scope": config.oauth_scope,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "prompt": "login",
    }
    return f"{AUTH_BASE}?{urlencode(params)}"


# ========================= 核心登录流程 =========================

@dataclass
class _LoginContext:
    account: Account
    config: "object"
    challenge: str
    verifier: str
    state: str


# Auth0 登录页的选择器集中定义，便于未来维护
SEL_EMAIL_INPUT = 'input[name="username"]'
SEL_PASSWORD_INPUT = 'input[name="password"]'
SEL_SUBMIT_BUTTON = 'button[type="submit"]'
SEL_TOTP_INPUT = 'input[name="code"], input[autocomplete="one-time-code"], input[type="tel"][maxlength="6"]'
SEL_ERROR_MESSAGE = '[class*="error"], [class*="alert"], .ulp-alert'


async def harvest_one(
    account: Account,
    config,
    on_success: Optional[OnSuccessCallback] = None,
) -> HarvestResult:
    """单账号完整 PKCE 流程。

    成功拿到 TokenSet 后，会立即调用 on_success（若传入）写入外部存储。
    rt 完整值不会出现在 HarvestResult 里（只保留前缀），以减少泄露风险。
    """
    from playwright.async_api import async_playwright  # 延迟导入，减少 CLI 冷启动

    verifier, challenge = generate_pkce_pair()
    state = generate_state()
    ctx = _LoginContext(account=account, config=config, challenge=challenge, verifier=verifier, state=state)

    profile_dir = _profile_dir_for(account.email, config)
    profile_dir.mkdir(parents=True, exist_ok=True)

    masked = account.masked_email()
    logger.info(f"[{masked}] 启动浏览器 (headless={config.headless}, profile={profile_dir.name})")

    try:
        async with async_playwright() as pw:
            launch_kwargs = {
                "user_data_dir": str(profile_dir),
                "headless": config.headless,
                "viewport": {"width": 1280, "height": 800},
                "locale": "en-US",
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if config.playwright_proxy:
                launch_kwargs["proxy"] = {"server": config.playwright_proxy}

            browser = await pw.chromium.launch_persistent_context(**launch_kwargs)
            try:
                page = await browser.new_page()
                code = await asyncio.wait_for(
                    _run_login_flow(page, ctx),
                    timeout=config.timeout_per_account_seconds,
                )
            finally:
                await browser.close()

        token_set = await exchange_code_for_tokens(code, ctx)
        logger.info(f"[{masked}] ✅ 成功 rt={token_set.rt_prefix}***")

        # 成功回调：让调用方立即处理 rt，oauth_flow 不保留
        if on_success:
            try:
                await on_success(account, token_set)
            except Exception as e:
                logger.error(f"[{masked}] on_success 回调异常: {e}")
                return HarvestResult.failure(account.email, f"post-import error: {e}")

        return HarvestResult.success(account.email, token_set, imported=on_success is not None)

    except asyncio.TimeoutError:
        logger.error(f"[{masked}] 超时（{config.timeout_per_account_seconds}s）")
        return HarvestResult.failure(account.email, "timeout")
    except HarvestError as e:
        logger.error(f"[{masked}] 失败：{e}")
        return HarvestResult.failure(account.email, str(e))
    except Exception as e:
        logger.exception(f"[{masked}] 未预期异常")
        return HarvestResult.failure(account.email, f"unexpected: {e}")


def _profile_dir_for(email: str, config) -> Path:
    h = hashlib.sha256(email.encode("utf-8")).hexdigest()[:16]
    return config.profiles_dir / h


class HarvestError(Exception):
    pass


# ========================= 登录步骤 =========================

async def _run_login_flow(page, ctx: _LoginContext) -> str:
    """执行完整登录流程，返回 authorization code。"""
    config = ctx.config
    account = ctx.account
    masked = account.masked_email()

    auth_url = build_authorize_url(ctx.challenge, ctx.state, config)
    logger.info(f"[{masked}] 打开 /authorize")
    await page.goto(auth_url, wait_until="domcontentloaded")

    # Step 1: email
    await _maybe_fill_email(page, account.email, masked)

    # Step 2: password
    await _maybe_fill_password(page, account.password, masked)

    # Step 3: 等待登录完成 (可能中途出现 Arkose / TOTP)
    callback_url = await _wait_for_callback_or_challenges(page, ctx)

    # Step 4: 从 URL 提取 code
    parsed = urlparse(callback_url)
    qs = parse_qs(parsed.query)
    code_list = qs.get("code")
    if not code_list:
        error = qs.get("error", ["unknown"])[0]
        desc = qs.get("error_description", [""])[0]
        raise HarvestError(f"未捕获到 authorization code: error={error} desc={desc}")
    return code_list[0]


async def _maybe_fill_email(page, email: str, masked: str) -> None:
    try:
        await page.wait_for_selector(SEL_EMAIL_INPUT, timeout=15000)
    except Exception:
        # 有时直接走到密码页（profile 里记住了邮箱）
        logger.info(f"[{masked}] 跳过邮箱输入（可能已记住）")
        return
    await page.fill(SEL_EMAIL_INPUT, email)
    logger.info(f"[{masked}] 已填邮箱")
    await page.click(SEL_SUBMIT_BUTTON)


async def _maybe_fill_password(page, password: str, masked: str) -> None:
    try:
        await page.wait_for_selector(SEL_PASSWORD_INPUT, timeout=15000)
    except Exception:
        raise HarvestError("未找到密码输入框（可能 Auth0 改版或账号不存在）")
    await page.fill(SEL_PASSWORD_INPUT, password)
    logger.info(f"[{masked}] 已填密码")
    await page.click(SEL_SUBMIT_BUTTON)


async def _wait_for_callback_or_challenges(page, ctx: _LoginContext) -> str:
    """同时监听：回调 URL / TOTP 输入框 / Arkose 挑战。"""
    config = ctx.config
    account = ctx.account
    masked = account.masked_email()

    callback_future = asyncio.Future()

    def on_framenav(frame):
        url = frame.url or ""
        if url.startswith(config.oauth_redirect_uri):
            if not callback_future.done():
                callback_future.set_result(url)

    page.on("framenavigated", on_framenav)

    deadline = time.time() + config.timeout_per_account_seconds
    totp_handled = False
    arkose_prompted_at = None

    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise HarvestError("等待登录完成超时")
        if callback_future.done():
            return callback_future.result()

        # 检查 TOTP 输入框（仅账号配了 totp_secret 时自动填）
        if not totp_handled and account.totp_secret:
            if await _try_fill_totp(page, account.totp_secret, masked):
                totp_handled = True
                continue

        # 检查 Arkose iframe
        arkose_visible = await _is_arkose_visible(page)
        if arkose_visible:
            if arkose_prompted_at is None:
                arkose_prompted_at = time.time()
                logger.warning(
                    f"[{masked}] ⚠️  检测到 Arkose 人机挑战，请在浏览器中手工完成；"
                    f"最多等待 {config.pause_for_arkose_seconds}s..."
                )
            elif time.time() - arkose_prompted_at > config.pause_for_arkose_seconds:
                raise HarvestError("Arkose 挑战未在规定时间内完成")

        # 检查错误提示（密码错、账号不存在等）
        err = await _read_error_text(page)
        if err:
            raise HarvestError(f"登录页报错：{err[:200]}")

        # 等一小会儿再轮询
        try:
            await asyncio.wait_for(asyncio.shield(callback_future), timeout=1.0)
        except asyncio.TimeoutError:
            continue


async def _try_fill_totp(page, secret: str, masked: str) -> bool:
    """检测到 TOTP 输入框则填入当前 6 位码，返回 True。"""
    try:
        input_handle = await page.query_selector(SEL_TOTP_INPUT)
    except Exception:
        return False
    if not input_handle:
        return False
    try:
        code = totp_code(secret)
    except Exception as e:
        logger.error(f"[{masked}] TOTP 生成失败: {e}")
        return False
    logger.info(f"[{masked}] 检测到 2FA 输入框，已自动填入 TOTP")
    await input_handle.fill(code)
    # 尝试找提交按钮（有些页面需手动按回车）
    try:
        await page.click(SEL_SUBMIT_BUTTON, timeout=2000)
    except Exception:
        await input_handle.press("Enter")
    return True


async def _is_arkose_visible(page) -> bool:
    """检测页面是否嵌入 arkoselabs iframe。"""
    try:
        frames = page.frames
    except Exception:
        return False
    for f in frames:
        url = (f.url or "").lower()
        if "arkoselabs" in url or "funcaptcha" in url:
            return True
    return False


async def _read_error_text(page) -> str:
    try:
        handle = await page.query_selector(SEL_ERROR_MESSAGE)
        if not handle:
            return ""
        text = (await handle.inner_text()).strip()
        return text
    except Exception:
        return ""


# ========================= Code → Token =========================

async def exchange_code_for_tokens(code: str, ctx: _LoginContext) -> TokenSet:
    """用 authorization code 向 Auth0 换 access/refresh token。"""
    config = ctx.config
    data = {
        "grant_type": "authorization_code",
        "client_id": config.oauth_client_id,
        "redirect_uri": config.oauth_redirect_uri,
        "code": code,
        "code_verifier": ctx.verifier,
    }
    logger.info(f"[{ctx.account.masked_email()}] 交换 code → tokens")

    proxies = config.playwright_proxy if config.playwright_proxy else None
    async with httpx.AsyncClient(timeout=30, proxies=proxies) as c:
        r = await c.post(
            TOKEN_ENDPOINT,
            json=data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "ChatGPT/1.2025.084 (iOS 17.5.1; iPhone15,3; build 1402)",
            },
        )
    if r.status_code != 200:
        raise HarvestError(
            f"Auth0 /oauth/token 失败 status={r.status_code}: {r.text[:300]}"
        )
    payload = r.json()
    if "refresh_token" not in payload:
        raise HarvestError(f"Auth0 响应缺 refresh_token: keys={list(payload.keys())}")
    return TokenSet(
        access_token=payload.get("access_token", ""),
        refresh_token=payload["refresh_token"],
        id_token=payload.get("id_token", ""),
        expires_in=int(payload.get("expires_in", 0)),
        token_type=payload.get("token_type", "Bearer"),
        scope=payload.get("scope", ""),
    )

