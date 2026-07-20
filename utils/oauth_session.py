"""OAuth PKCE session 管理（纯内存 + TTL）。

用于 Harvester 的"浏览器登录"流程：
  1. start(email, ...) → 生成 PKCE + state + session_id，存入内存，返回 authorize_url
  2. 用户在真实浏览器完成 OAuth，拿到 com.openai.chat://...?code=X&state=Y 回调
  3. exchange(session_id, callback_url) → 校验 state + 用 verifier 换 token

设计：
  - 内存 dict，不持久化（服务重启即失效，符合用户选择）
  - 15 分钟 TTL（Auth0 的 code 也是 ~10 分钟过期）
  - 线程安全（threading.Lock）
  - 自动清理过期会话（每次写操作时机会性清理）
"""

import base64
import hashlib
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional
from urllib.parse import urlencode


# 与 Codex CLI 一致的新版配置（claude-relay-service 已验证可用）
# 老版 iOS app (pdlLIX... + auth0.openai.com) 已失效，返回 404
_DEFAULT_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
_DEFAULT_REDIRECT_URI = "http://localhost:1455/auth/callback"
_DEFAULT_AUDIENCE = "https://api.openai.com/v1"
_DEFAULT_SCOPE = "openid profile email offline_access"
_DEFAULT_AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
_DEFAULT_TOKEN_ENDPOINT = "https://auth.openai.com/oauth/token"

# 向后兼容：保留老常量名（TOKEN_ENDPOINT 被外部引用）
AUTH_BASE = _DEFAULT_AUTHORIZE_URL
TOKEN_ENDPOINT = _DEFAULT_TOKEN_ENDPOINT

SESSION_TTL_SECONDS = 15 * 60


@dataclass
class OAuthSession:
    session_id: str
    verifier: str
    challenge: str
    state: str
    email: str
    note: str = ""
    proxy_name: str = ""
    created_at: int = field(default_factory=lambda: int(time.time()))

    def expired(self) -> bool:
        return time.time() - self.created_at > SESSION_TTL_SECONDS


# ========================= 内存存储 =========================

_sessions: Dict[str, OAuthSession] = {}
_lock = threading.Lock()


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _gen_pkce_pair() -> tuple:
    verifier = _base64url(secrets.token_bytes(32))
    challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _gen_state() -> str:
    return _base64url(secrets.token_bytes(16))


def _gen_session_id() -> str:
    return _base64url(secrets.token_bytes(12))


def _gc_expired() -> None:
    """机会性清理过期会话，调用方需已持锁。"""
    now = time.time()
    expired = [
        sid for sid, s in _sessions.items()
        if now - s.created_at > SESSION_TTL_SECONDS
    ]
    for sid in expired:
        _sessions.pop(sid, None)


# ========================= 对外 API =========================

def _get_oauth_config():
    """允许通过 configs 覆盖 client_id / redirect_uri / endpoints。返回 7-tuple。"""
    try:
        from utils import configs
        client_id = getattr(configs, "openai_auth_client_id", None) or _DEFAULT_CLIENT_ID
        redirect_uri = getattr(configs, "openai_auth_redirect_uri", None) or _DEFAULT_REDIRECT_URI
        audience = getattr(configs, "openai_auth_audience", None) or _DEFAULT_AUDIENCE
        scope = getattr(configs, "openai_auth_scope", None) or _DEFAULT_SCOPE
        authorize_url = getattr(configs, "openai_auth_authorize_url", None) or _DEFAULT_AUTHORIZE_URL
        token_url = getattr(configs, "openai_auth_token_url", None) or _DEFAULT_TOKEN_ENDPOINT
    except Exception:
        client_id = _DEFAULT_CLIENT_ID
        redirect_uri = _DEFAULT_REDIRECT_URI
        audience = _DEFAULT_AUDIENCE
        scope = _DEFAULT_SCOPE
        authorize_url = _DEFAULT_AUTHORIZE_URL
        token_url = _DEFAULT_TOKEN_ENDPOINT
    return client_id, redirect_uri, audience, scope, authorize_url, token_url


def start_session(email: str, note: str = "", proxy_name: str = "") -> Dict:
    """生成一次性 OAuth 授权会话，返回前端需要的 URL + session_id。"""
    if not email or "@" not in email:
        raise ValueError("email 不合法")

    client_id, redirect_uri, audience, scope, authorize_url, _token_url = _get_oauth_config()

    verifier, challenge = _gen_pkce_pair()
    state = _gen_state()
    session_id = _gen_session_id()

    sess = OAuthSession(
        session_id=session_id,
        verifier=verifier,
        challenge=challenge,
        state=state,
        email=email.strip(),
        note=(note or "").strip(),
        proxy_name=(proxy_name or "").strip(),
    )
    with _lock:
        _gc_expired()
        _sessions[session_id] = sess

    # Codex CLI 风格的 query 参数（额外参数让 OpenAI 返回 organization 信息）
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
    }
    full_url = f"{authorize_url}?{urlencode(params)}"
    return {
        "session_id": session_id,
        "authorize_url": full_url,
        "redirect_uri": redirect_uri,
        "expires_in": SESSION_TTL_SECONDS,
    }


def pop_session(session_id: str) -> Optional[OAuthSession]:
    """取出并删除会话（一次性使用）。过期返回 None。"""
    with _lock:
        sess = _sessions.pop(session_id, None)
    if not sess:
        return None
    if sess.expired():
        return None
    return sess


def peek_session(session_id: str) -> Optional[OAuthSession]:
    """不删除地查看会话（供调试）。"""
    with _lock:
        sess = _sessions.get(session_id)
    if sess and sess.expired():
        return None
    return sess


def stats() -> Dict:
    with _lock:
        _gc_expired()
        total = len(_sessions)
    return {"active_sessions": total, "ttl_seconds": SESSION_TTL_SECONDS}
