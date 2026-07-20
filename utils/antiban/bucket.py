"""IP-账号终身粘性桶。

核心不变量：
  1. 一个账号 token 一旦首次绑定到某个桶（IP），**永不漂移**到其他桶；
  2. 桶可在状态 healthy/degraded/dead 间切换，桶内账号一律跟随桶，不会在运行时被重分配；
  3. 分配策略：新账号选择"已有账号最少 & healthy"的桶，容量上限由 BUCKET_MAX_ACCOUNTS_PER_IP 控制；
  4. routing.py 的 bindings 作为桶的唯一数据源；antiban_bucket.json 只保存运行期状态（last_request_at、status）。
"""

import json
import threading
import time
from typing import Dict, List, Optional, Tuple

import utils.globals as globals
from utils import configs
from utils.Logger import logger
from utils.routing import get_routing_config, update_single_binding

_write_lock = threading.Lock()


def _persist() -> None:
    with _write_lock:
        with open(globals.ANTIBAN_BUCKET_FILE, "w", encoding="utf-8") as f:
            json.dump(globals.antiban_bucket, f, indent=2, ensure_ascii=False)


def _ensure_structure() -> None:
    globals.antiban_bucket.setdefault("buckets", {})
    globals.antiban_bucket.setdefault("account_index", {})


def _now() -> int:
    return int(time.time())


def _bucket_id_for_proxy(proxy_url: str) -> str:
    return f"bkt::{proxy_url}"


def _sync_from_routing() -> None:
    """把 routing_config.json 中已存在的 bindings 吸收到桶里（幂等）。"""
    _ensure_structure()
    routing = get_routing_config()
    bindings = routing.get("bindings", {})
    if not bindings:
        return
    changed = False
    for token, binding in bindings.items():
        proxy_url = binding.get("proxy_url")
        if not proxy_url:
            continue
        bucket_id = _bucket_id_for_proxy(proxy_url)
        bucket = globals.antiban_bucket["buckets"].setdefault(bucket_id, {
            "proxy_url": proxy_url,
            "proxy_name": binding.get("proxy_name", ""),
            "group": binding.get("group", ""),
            "accounts": [],
            "last_request_at": {},
            "status": "healthy",
            "degraded_until": 0,
            "created_at": _now(),
        })
        if token not in bucket["accounts"]:
            bucket["accounts"].append(token)
            changed = True
        if globals.antiban_bucket["account_index"].get(token) != bucket_id:
            globals.antiban_bucket["account_index"][token] = bucket_id
            changed = True
    if changed:
        _persist()
        logger.info(f"[antiban] synced {len(bindings)} routing bindings into buckets")


def _pick_least_loaded_healthy() -> Optional[Tuple[str, Dict]]:
    """返回 (bucket_id, bucket) 中账号最少且 healthy、未满的桶。"""
    cap = configs.bucket_max_accounts_per_ip
    candidates = []
    for bucket_id, bucket in globals.antiban_bucket["buckets"].items():
        if bucket.get("status") != "healthy":
            continue
        size = len(bucket.get("accounts", []))
        if size >= cap:
            continue
        candidates.append((size, bucket_id, bucket))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    _, bucket_id, bucket = candidates[0]
    return bucket_id, bucket


def assign_account(token: str) -> Optional[str]:
    """核心分配函数。已绑定 → 直接返回桶 id；未绑定 → 选最空 healthy 桶 & 写入 routing_config。"""
    if not configs.enable_antiban or not token:
        return None
    _ensure_structure()

    existing = globals.antiban_bucket["account_index"].get(token)
    if existing and existing in globals.antiban_bucket["buckets"]:
        return existing

    # 首次同步 routing 作为冷启动保底
    if not globals.antiban_bucket["buckets"]:
        _sync_from_routing()
        existing = globals.antiban_bucket["account_index"].get(token)
        if existing:
            return existing

    pick = _pick_least_loaded_healthy()
    if not pick:
        # 所有桶都满了/不健康；严格模式拒绝漂移；宽松模式 → 拒绝分配让上游走默认
        if configs.strict_ip_binding:
            logger.warning(
                f"[antiban] no healthy bucket for token {token[:12]}... "
                f"(strict_ip_binding=True); caller must handle"
            )
        return None

    bucket_id, bucket = pick
    bucket["accounts"].append(token)
    bucket.setdefault("last_request_at", {})[token] = 0
    globals.antiban_bucket["account_index"][token] = bucket_id
    _persist()

    # 同步回 routing_config.json，保持跨重启一致
    try:
        update_single_binding(
            token,
            proxy_name=bucket.get("proxy_name", ""),
            proxy_url=bucket.get("proxy_url", ""),
            group_name=bucket.get("group") or None,
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"[antiban] failed to persist binding to routing_config: {e}")

    logger.info(
        f"[antiban] token {token[:12]}... assigned to bucket "
        f"{bucket.get('proxy_name','?')} ({len(bucket['accounts'])}/{configs.bucket_max_accounts_per_ip})"
    )
    return bucket_id


def get_bucket_proxy(token: str) -> Optional[str]:
    if not configs.enable_antiban or not token:
        return None
    _ensure_structure()
    bucket_id = globals.antiban_bucket["account_index"].get(token)
    if not bucket_id:
        return None
    bucket = globals.antiban_bucket["buckets"].get(bucket_id, {})
    return bucket.get("proxy_url")


def get_bucket_meta(bucket_id: Optional[str]) -> Dict:
    if not bucket_id:
        return {}
    return globals.antiban_bucket.get("buckets", {}).get(bucket_id, {})


def mark_used(token: str) -> None:
    if not configs.enable_antiban or not token:
        return
    _ensure_structure()
    bucket_id = globals.antiban_bucket["account_index"].get(token)
    if not bucket_id:
        return
    bucket = globals.antiban_bucket["buckets"].get(bucket_id)
    if not bucket:
        return
    bucket.setdefault("last_request_at", {})[token] = _now()
    # 写盘频率控制：每 5 次请求批量刷一次，避免 I/O 瓶颈
    bucket["_dirty_count"] = bucket.get("_dirty_count", 0) + 1
    if bucket["_dirty_count"] >= 5:
        bucket["_dirty_count"] = 0
        _persist()


def degrade_bucket(bucket_id: str, seconds: int) -> None:
    if not bucket_id or bucket_id not in globals.antiban_bucket.get("buckets", {}):
        return
    bucket = globals.antiban_bucket["buckets"][bucket_id]
    bucket["status"] = "degraded"
    bucket["degraded_until"] = _now() + seconds
    _persist()
    logger.warning(f"[antiban] bucket {bucket_id} degraded for {seconds}s")


def heal_buckets() -> int:
    """定时任务：把已过冷却时间的 degraded 桶恢复为 healthy。返回恢复数量。"""
    _ensure_structure()
    restored = 0
    now = _now()
    for bucket in globals.antiban_bucket["buckets"].values():
        if bucket.get("status") == "degraded" and bucket.get("degraded_until", 0) <= now:
            bucket["status"] = "healthy"
            bucket["degraded_until"] = 0
            restored += 1
    if restored:
        _persist()
        logger.info(f"[antiban] healed {restored} degraded bucket(s)")
    return restored


def get_bucket_stats() -> Dict[str, int]:
    _ensure_structure()
    buckets = globals.antiban_bucket["buckets"]
    return {
        "bucket_count": len(buckets),
        "account_total": sum(len(b.get("accounts", [])) for b in buckets.values()),
        "healthy": sum(1 for b in buckets.values() if b.get("status") == "healthy"),
        "degraded": sum(1 for b in buckets.values() if b.get("status") == "degraded"),
    }


def bulk_assign(tokens: List[str]) -> Dict[str, int]:
    """应用启动时批量分配已加载的 tokens。"""
    if not configs.enable_antiban:
        return {"assigned": 0, "skipped": 0}
    _ensure_structure()
    _sync_from_routing()

    assigned = skipped = 0
    for token in tokens:
        if not token:
            continue
        if globals.antiban_bucket["account_index"].get(token):
            skipped += 1
            continue
        if assign_account(token):
            assigned += 1
        else:
            skipped += 1
    logger.info(f"[antiban] bulk_assign result: assigned={assigned} skipped={skipped}")
    return {"assigned": assigned, "skipped": skipped}


def resync_from_routing() -> Dict[str, int]:
    """热同步：routing_config.json 改动后调用，重建桶索引并重新分配未绑定账号。

    清除已不存在的代理对应的桶（保留桶历史 metadata 但标记为 dead）。
    """
    if not configs.enable_antiban:
        return {"synced": 0}
    _ensure_structure()

    # 1. 从 routing 重新导入 bindings
    _sync_from_routing()

    # 2. 清理：routing 里已不存在的 proxy_url 对应的桶标记为 dead
    routing = get_routing_config()
    valid_proxy_urls = {p.get("proxy_url") for p in routing.get("proxies", []) if p.get("proxy_url")}
    dead_count = 0
    for bucket_id, bucket in globals.antiban_bucket["buckets"].items():
        if bucket.get("proxy_url") not in valid_proxy_urls:
            if bucket.get("status") != "dead":
                bucket["status"] = "dead"
                dead_count += 1

    # 3. 清理孤儿 account_index（对应的桶已消失）
    orphaned = [tk for tk, bid in globals.antiban_bucket["account_index"].items()
                if bid not in globals.antiban_bucket["buckets"]]
    for tk in orphaned:
        globals.antiban_bucket["account_index"].pop(tk, None)

    # 4. 已存在 token 但未在任何桶 → 尝试重新分配到 healthy 桶
    reassigned = 0
    for token in list(globals.token_list):
        if not token:
            continue
        if globals.antiban_bucket["account_index"].get(token):
            continue
        if assign_account(token):
            reassigned += 1

    _persist()
    logger.info(
        f"[antiban] resync_from_routing: "
        f"dead_buckets={dead_count}, orphaned={len(orphaned)}, reassigned={reassigned}"
    )
    return {
        "dead_buckets": dead_count,
        "orphaned": len(orphaned),
        "reassigned": reassigned,
    }
