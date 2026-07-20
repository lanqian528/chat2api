"""账号级冷却与请求节奏。

行为：
  wait_or_skip(token) → 若 next_available > now + max_wait, 立即返回 False；
                         否则 asyncio.sleep 到可用并返回 True；
                         同 token 并发请求会串行（通过 _get_lock）。
  record_request(token) → 把 next_available 设到 now + interval * (1 ± jitter)；
                           在请求"成功"后调用（antiban.guard.report_success 内部触发）。
  extend_cooldown(token, sec) → 429/403 时强制延长冷却。
"""

import asyncio
import random
import time
from typing import Dict, Optional

from utils import configs
from utils.Logger import logger

_account_next_available: Dict[str, float] = {}
_account_locks: Dict[str, asyncio.Lock] = {}


def _get_lock(token: str) -> asyncio.Lock:
    lock = _account_locks.get(token)
    if lock is None:
        lock = asyncio.Lock()
        _account_locks[token] = lock
    return lock


def _resolve_interval(token: str, persona: Optional[str] = None) -> int:
    """Team/Plus persona → 较短间隔；free/未知 → 较长间隔。"""
    if persona == "chatgpt-freeaccount":
        return configs.free_account_min_interval_seconds
    return configs.account_min_interval_seconds


async def wait_or_skip(token: str, persona: Optional[str] = None, max_wait: Optional[int] = None) -> bool:
    if not configs.enable_antiban or not token:
        return True

    max_wait_seconds = max_wait if max_wait is not None else configs.account_max_wait_seconds
    now = time.time()
    next_at = _account_next_available.get(token, 0.0)
    remaining = next_at - now

    if remaining <= 0:
        return True

    if remaining > max_wait_seconds:
        logger.info(
            f"[antiban] cooldown skip token={token[:12]}... "
            f"remaining={remaining:.1f}s > max_wait={max_wait_seconds}s"
        )
        return False

    # 串行化同 token 的并发请求，避免"3 个协程同时读到未冷却"
    async with _get_lock(token):
        now = time.time()
        remaining = _account_next_available.get(token, 0.0) - now
        if remaining > 0:
            logger.info(f"[antiban] cooldown sleep token={token[:12]}... {remaining:.1f}s")
            await asyncio.sleep(remaining)
        return True


def record_request(token: str, persona: Optional[str] = None, min_interval: Optional[int] = None) -> None:
    if not configs.enable_antiban or not token:
        return
    interval = min_interval if min_interval is not None else _resolve_interval(token, persona)
    jitter = configs.account_cooldown_jitter
    delta = interval * (1 + random.uniform(-jitter, jitter))
    _account_next_available[token] = time.time() + max(0.0, delta)


def extend_cooldown(token: str, seconds: int) -> None:
    if not token or seconds <= 0:
        return
    now = time.time()
    current = _account_next_available.get(token, now)
    _account_next_available[token] = max(current, now + seconds)
    logger.info(f"[antiban] cooldown extended token={token[:12]}... +{seconds}s")


def get_next_available(token: str) -> float:
    return _account_next_available.get(token, 0.0)
