"""Harvester 账号元数据：chat2api 后台与 Harvester 之间共享的"账号清单"。

只存**非敏感字段**：
  - email
  - note
  - proxy_name
  - last_rt_prefix   (最近一次采集到的 rt 前缀 8 字符)
  - last_harvest_at  (unix ts)
  - last_error       (最近一次失败原因)
  - fail_count
  - imported_token   (data/token.txt 中对应的完整 rt；用于 UI 查找)

**绝不存密码 / TOTP secret**。密码始终在用户 Mac 本地 harvester/accounts.csv。

持久化文件：data/harvester_accounts.json
"""

import json
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import utils.globals as globals
from utils.Logger import logger


_write_lock = threading.Lock()

# 状态阈值（秒）
FRESH_WITHIN = 7 * 24 * 3600         # 最近 7 天内采集 → fresh
STALE_WITHIN = 45 * 24 * 3600        # 超过 7 天 <= 45 天 → stale
# 超过 45 天未采集或 last_error → failed


def _load() -> Dict:
    path = Path(globals.HARVESTER_ACCOUNTS_FILE)
    if not path.exists():
        return {"accounts": {}, "updated_at": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("accounts", {})
        return data
    except (json.JSONDecodeError, OSError):
        return {"accounts": {}, "updated_at": 0}


def _save(data: Dict) -> None:
    data["updated_at"] = int(time.time())
    with _write_lock:
        Path(globals.HARVESTER_ACCOUNTS_FILE).write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def _email_key(email: str) -> str:
    return (email or "").strip().lower()


def _compute_status(rec: Dict) -> str:
    last_ts = rec.get("last_harvest_at", 0) or 0
    if rec.get("last_error") and not rec.get("last_rt_prefix"):
        return "failed"
    if not last_ts:
        return "pending"
    age = time.time() - last_ts
    if age < FRESH_WITHIN:
        return "fresh"
    if age < STALE_WITHIN:
        return "stale"
    return "failed"


def list_all() -> List[Dict]:
    """返回账号列表，按 email 排序，带计算字段 status。"""
    data = _load()
    items = []
    for email_lower, rec in data.get("accounts", {}).items():
        out = dict(rec)
        out["email"] = rec.get("email", email_lower)
        out["status"] = _compute_status(rec)
        items.append(out)
    items.sort(key=lambda x: x["email"].lower())
    return items


def get(email: str) -> Optional[Dict]:
    key = _email_key(email)
    if not key:
        return None
    data = _load()
    rec = data.get("accounts", {}).get(key)
    if not rec:
        return None
    out = dict(rec)
    out["status"] = _compute_status(rec)
    return out


def upsert(email: str, note: str = "", proxy_name: str = "") -> Dict:
    """新增或更新账号元数据（只改 email/note/proxy_name，不动采集历史）。"""
    key = _email_key(email)
    if not key or "@" not in key:
        raise ValueError("invalid email")
    data = _load()
    rec = data["accounts"].get(key, {"created_at": int(time.time())})
    rec["email"] = email.strip()
    rec["note"] = (note or "").strip()
    rec["proxy_name"] = (proxy_name or "").strip()
    rec.setdefault("last_rt_prefix", "")
    rec.setdefault("last_harvest_at", 0)
    rec.setdefault("last_error", "")
    rec.setdefault("fail_count", 0)
    rec.setdefault("imported_token", "")
    data["accounts"][key] = rec
    _save(data)
    return dict(rec)


def bulk_upsert(rows: List[Dict]) -> Dict[str, int]:
    """批量导入 [{email, note?, proxy_name?}]，返回 {added, updated}。"""
    data = _load()
    added = updated = 0
    for row in rows:
        email = (row.get("email") or "").strip()
        key = _email_key(email)
        if not key or "@" not in key:
            continue
        existed = key in data["accounts"]
        rec = data["accounts"].get(key, {"created_at": int(time.time())})
        rec["email"] = email
        rec["note"] = (row.get("note") or rec.get("note", "")).strip()
        rec["proxy_name"] = (row.get("proxy_name") or rec.get("proxy_name", "")).strip()
        rec.setdefault("last_rt_prefix", "")
        rec.setdefault("last_harvest_at", 0)
        rec.setdefault("last_error", "")
        rec.setdefault("fail_count", 0)
        rec.setdefault("imported_token", "")
        data["accounts"][key] = rec
        if existed:
            updated += 1
        else:
            added += 1
    _save(data)
    return {"added": added, "updated": updated}


def delete(email: str) -> bool:
    """从元数据中删除账号（不影响 data/token.txt 中的 token）。"""
    key = _email_key(email)
    data = _load()
    if key in data["accounts"]:
        data["accounts"].pop(key)
        _save(data)
        return True
    return False


def report_harvest(
    email: str,
    rt_prefix: str = "",
    success: bool = True,
    error: str = "",
    imported_token: str = "",
) -> Dict:
    """Harvester 成功/失败后上报。若 email 未知则自动创建。"""
    key = _email_key(email)
    if not key or "@" not in key:
        raise ValueError("invalid email")
    data = _load()
    rec = data["accounts"].get(key, {
        "email": email.strip(),
        "note": "",
        "proxy_name": "",
        "created_at": int(time.time()),
    })
    rec["email"] = email.strip()
    now = int(time.time())
    if success:
        rec["last_rt_prefix"] = (rt_prefix or "")[:12]
        rec["last_harvest_at"] = now
        rec["last_error"] = ""
        rec["fail_count"] = 0
        if imported_token:
            rec["imported_token"] = imported_token
    else:
        rec["last_error"] = (error or "unknown")[:200]
        rec["last_error_at"] = now
        rec["fail_count"] = int(rec.get("fail_count", 0)) + 1
    data["accounts"][key] = rec
    _save(data)
    logger.info(
        f"[harvester-meta] report email={email} success={success} "
        f"rt_prefix={rt_prefix[:8] if rt_prefix else ''}..."
    )
    return dict(rec)


def stats() -> Dict:
    """总览数据，供 UI 顶部卡片使用。"""
    items = list_all()
    return {
        "total": len(items),
        "fresh": sum(1 for x in items if x["status"] == "fresh"),
        "stale": sum(1 for x in items if x["status"] == "stale"),
        "failed": sum(1 for x in items if x["status"] == "failed"),
        "pending": sum(1 for x in items if x["status"] == "pending"),
    }
