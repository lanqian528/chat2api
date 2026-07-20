"""熔断与黑名单自愈。

错误分级：
  403 + cf_chl_opt   → bucket 降级 CIRCUIT_403_COOLDOWN；桶内账号一并延长冷却
  429 rate-limit     → 账号指数退避冷却（60→300→1800→7200s 封顶）
  401 invalid_grant  → 加入 error_token_list，等 refreshToken 恢复
  account_deactivated→ 永久黑名单 antiban_dead.json
  200 成功           → 重置账号退避等级
"""

import json
import threading
import time
from typing import Optional

import utils.globals as globals
from utils import configs
from utils.antiban import bucket as _bucket
from utils.antiban import cooldown
from utils.Logger import logger

_write_lock = threading.Lock()

_account_backoff_level = {}  # token -> 0..N
_bucket_network_errors = {}  # bucket_id -> 连续网络层错误计数（连接超时/拒绝/DNS）

# 同一桶连续网络层错误阈值；达到后降级 300s（代理本身可能挂了）
_NETWORK_ERROR_THRESHOLD = 3
_NETWORK_ERROR_COOLDOWN = 300


def _persist_dead() -> None:
    with _write_lock:
        with open(globals.ANTIBAN_DEAD_FILE, "w", encoding="utf-8") as f:
            json.dump(globals.antiban_dead_tokens, f, indent=2, ensure_ascii=False)


def is_bucket_allowed(bucket_id: Optional[str]) -> bool:
    if not bucket_id:
        return True
    meta = _bucket.get_bucket_meta(bucket_id)
    if meta.get("status") == "degraded":
        if meta.get("degraded_until", 0) > int(time.time()):
            return False
    return True


def is_token_dead(token: str) -> bool:
    return token in globals.antiban_dead_tokens


def mark_dead(token: str, reason: str = "") -> None:
    if not token:
        return
    globals.antiban_dead_tokens[token] = {
        "reason": reason,
        "dead_at": int(time.time()),
    }
    try:
        _persist_dead()
    except Exception as e:  # pragma: no cover
        logger.error(f"[antiban] failed to persist dead token: {e}")
    logger.error(f"[antiban] token {token[:12]}... marked dead: {reason}")


def reset_backoff(token: str) -> None:
    _account_backoff_level.pop(token, None)


def bump_backoff(token: str) -> int:
    level = _account_backoff_level.get(token, 0) + 1
    _account_backoff_level[token] = level
    return level


def _cooldown_bucket_accounts(bucket_id: str, seconds: int) -> None:
    """IP 桶降级时，给桶内所有账号加一次冷却延长，避免下次还用该桶相关账号立刻命中。"""
    meta = _bucket.get_bucket_meta(bucket_id)
    for token in meta.get("accounts", []):
        cooldown.extend_cooldown(token, seconds)


def handle_response_error(token: str, bucket_id: Optional[str], status_code: int, detail) -> None:
    if not configs.enable_antiban:
        return
    detail_str = (str(detail) if detail is not None else "").lower()

    # Cloudflare 挑战 → 整桶降级
    if status_code == 403 and "cf_chl_opt" in detail_str:
        if bucket_id:
            _bucket.degrade_bucket(bucket_id, configs.circuit_403_cooldown)
            _cooldown_bucket_accounts(bucket_id, configs.circuit_403_cooldown)
        return

    # 频控 → 账号指数退避
    if status_code == 429 or "rate-limit" in detail_str:
        level = bump_backoff(token)
        base = configs.circuit_429_cooldown
        cooldown.extend_cooldown(token, min(base * (2 ** (level - 1)), 7200))
        return

    # 刷新凭据失效 → error_token_list（refreshToken 流程会尝试恢复）
    if status_code == 401 and ("invalid_grant" in detail_str or "unauthorized" in detail_str):
        if token and token not in globals.error_token_list:
            globals.error_token_list.append(token)
        return

    # 账号停用/封禁 → 永久黑名单
    if "account_deactivated" in detail_str or "banned" in detail_str:
        mark_dead(token, detail_str[:120])
        return

    # 其他 5xx：不立即降级，但轻度退避（避免风暴）
    if 500 <= status_code < 600 and token:
        cooldown.extend_cooldown(token, 30)


def handle_response_success(token: str) -> None:
    if not configs.enable_antiban:
        return
    reset_backoff(token)


def handle_network_error(token: str, bucket_id: Optional[str], error_kind: str = "") -> None:
    """M3: 网络层错误（连接被拒/超时/DNS 失败）连续 N 次 → 标记代理桶不健康。

    与 handle_response_error 区分：那是 HTTP 状态码，这是 transport 失败。
    """
    if not configs.enable_antiban or not bucket_id:
        return
    count = _bucket_network_errors.get(bucket_id, 0) + 1
    _bucket_network_errors[bucket_id] = count
    if count >= _NETWORK_ERROR_THRESHOLD:
        _bucket.degrade_bucket(bucket_id, _NETWORK_ERROR_COOLDOWN)
        _cooldown_bucket_accounts(bucket_id, _NETWORK_ERROR_COOLDOWN)
        _bucket_network_errors[bucket_id] = 0
        logger.warning(
            f"[antiban] bucket {bucket_id} degraded due to {_NETWORK_ERROR_THRESHOLD}x network errors "
            f"(last={error_kind or 'unknown'})"
        )


def reset_network_errors(bucket_id: Optional[str]) -> None:
    """成功响应后清空网络错误计数。"""
    if bucket_id and bucket_id in _bucket_network_errors:
        _bucket_network_errors.pop(bucket_id, None)


async def scheduled_heal() -> None:
    """定时任务入口：由 APScheduler 调用。"""
    restored = _bucket.heal_buckets()
    if restored:
        logger.info(f"[antiban] scheduled_heal restored {restored} bucket(s)")
