"""LibreChat 会话粘性：LibreChat conv_id ↔ ChatGPT conv_id 翻译层。

设计 (KISS / YAGNI / DRY)：
  - SQLite 单表持久化映射；WAL 模式 + 短连接，async 友好
  - 入口 inject_session：命中映射 → 在 request_data 注入 conversation_id / parent_message_id；
                         未命中 → 不动 body，让 ChatService 走"新建对话"流程
  - 出口 sniff_and_save：流式响应每个 chunk 含 conv_id / message_id 时回写 DB
  - 不影响现有逻辑：开关 enable_session_sticky 关闭时所有 API 直接 return

外部 API：
  init_db()
  inject_session(request_data) -> Optional[str]   # 返回 lc_conv_id 用于后续嗅探
  sniff_and_save(lc_conv_id, chatgpt_conv_id, parent_msg_id)
  drop_mapping(lc_conv_id)                         # 命中后 ChatGPT 返回 404 时清理
  cleanup_expired()                                # 超 TTL 自动清理
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Optional, Tuple

from utils.Logger import logger
from utils import configs

_DB_INITIALIZED = False
_INIT_LOCK = threading.Lock()
_WRITE_LOCK = threading.Lock()  # 避免并发写竞争 (uvicorn 单 worker async 通常不需要，但 worker>1 时保险)


def _enabled() -> bool:
    return bool(getattr(configs, "enable_session_sticky", False))


def _db_path() -> str:
    return getattr(configs, "session_db_path", "data/sessions.db")


def _lc_field() -> str:
    return getattr(configs, "session_lc_field", "librechat_conversation_id")


def _connect() -> sqlite3.Connection:
    path = _db_path()
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


def init_db() -> None:
    """容器启动时调用一次。多次调用安全。"""
    global _DB_INITIALIZED
    if not _enabled():
        return
    with _INIT_LOCK:
        if _DB_INITIALIZED:
            return
        try:
            with _connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS lc_session_map (
                        librechat_conv_id TEXT PRIMARY KEY,
                        chatgpt_conv_id   TEXT NOT NULL,
                        parent_msg_id     TEXT,
                        created_at        INTEGER NOT NULL,
                        updated_at        INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_lc_updated ON lc_session_map(updated_at)"
                )
            _DB_INITIALIZED = True
            logger.info(f"[session_sticky] db ready at {_db_path()}")
        except Exception as e:
            logger.error(f"[session_sticky] init failed: {e}")


def _get_mapping(lc_conv_id: str) -> Optional[Tuple[str, Optional[str]]]:
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT chatgpt_conv_id, parent_msg_id FROM lc_session_map WHERE librechat_conv_id=?",
                (lc_conv_id,),
            ).fetchone()
            return (row[0], row[1]) if row else None
    except Exception as e:
        logger.error(f"[session_sticky] get_mapping error: {e}")
        return None


def _upsert_mapping(lc_conv_id: str, chatgpt_conv_id: str, parent_msg_id: Optional[str]) -> None:
    now = int(time.time())
    try:
        with _WRITE_LOCK, _connect() as conn:
            conn.execute(
                """
                INSERT INTO lc_session_map (librechat_conv_id, chatgpt_conv_id, parent_msg_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(librechat_conv_id) DO UPDATE SET
                    chatgpt_conv_id = excluded.chatgpt_conv_id,
                    parent_msg_id   = excluded.parent_msg_id,
                    updated_at      = excluded.updated_at
                """,
                (lc_conv_id, chatgpt_conv_id, parent_msg_id, now, now),
            )
    except Exception as e:
        logger.error(f"[session_sticky] upsert_mapping error: {e}")


def drop_mapping(lc_conv_id: str) -> None:
    """ChatGPT 返回 404 / conv_id 失效时清理。下次同 lc_conv_id 会新建对话。"""
    if not _enabled() or not lc_conv_id:
        return
    try:
        with _WRITE_LOCK, _connect() as conn:
            conn.execute("DELETE FROM lc_session_map WHERE librechat_conv_id=?", (lc_conv_id,))
        logger.info(f"[session_sticky] dropped mapping for {lc_conv_id[:12]}...")
    except Exception as e:
        logger.error(f"[session_sticky] drop_mapping error: {e}")


def cleanup_expired() -> int:
    """删除超过 TTL 未更新的映射；返回删除条数。"""
    if not _enabled():
        return 0
    ttl_days = int(getattr(configs, "session_ttl_days", 30))
    cutoff = int(time.time()) - ttl_days * 86400
    try:
        with _WRITE_LOCK, _connect() as conn:
            cur = conn.execute("DELETE FROM lc_session_map WHERE updated_at < ?", (cutoff,))
            deleted = cur.rowcount or 0
        if deleted:
            logger.info(f"[session_sticky] cleanup_expired removed {deleted} rows")
        return deleted
    except Exception as e:
        logger.error(f"[session_sticky] cleanup_expired error: {e}")
        return 0


def inject_session(request_data: dict) -> Optional[str]:
    """请求入口注入。

    返回：
      lc_conv_id（用于后续 sniff_and_save 回写）；功能未启用或请求体无 lc_conv_id 时返回 None。

    副作用：
      命中映射 → 写入 request_data['conversation_id'] / ['parent_message_id']
              → 默认把 messages 截到只保留最后一条 user message（节省 token，
                依赖 ChatGPT 服务端续接历史）
    """
    if not _enabled() or not isinstance(request_data, dict):
        return None
    lc_conv_id = request_data.get(_lc_field())
    if not lc_conv_id or not isinstance(lc_conv_id, str):
        return None

    init_db()  # 懒初始化
    mapping = _get_mapping(lc_conv_id)
    if not mapping:
        # 首次见到该 lc_conv_id；让 ChatGPT 创建新 conv，嗅探阶段再回写
        logger.info(f"[session_sticky] miss lc={lc_conv_id[:12]}... → new conv")
        return lc_conv_id

    chatgpt_conv_id, parent_msg_id = mapping
    # 仅当用户没有显式传入 conversation_id 时才注入（用户显式传入优先级最高）
    if not request_data.get("conversation_id"):
        request_data["conversation_id"] = chatgpt_conv_id
    if parent_msg_id and not request_data.get("parent_message_id"):
        request_data["parent_message_id"] = parent_msg_id
    # 续接 ChatGPT 端历史 → 强制 history_disabled=False
    request_data["history_disabled"] = False

    # 截短 messages：仅保留最后一条 user message + 可选 system
    if getattr(configs, "session_trim_to_last_user", True):
        msgs = request_data.get("messages") or []
        if isinstance(msgs, list) and len(msgs) > 1:
            trimmed = []
            # 保留首条 system（若有）
            if msgs and isinstance(msgs[0], dict) and msgs[0].get("role") == "system":
                trimmed.append(msgs[0])
            # 取最后一条 user
            last_user = next(
                (m for m in reversed(msgs) if isinstance(m, dict) and m.get("role") == "user"),
                None,
            )
            if last_user:
                trimmed.append(last_user)
                request_data["messages"] = trimmed

    logger.info(
        f"[session_sticky] hit lc={lc_conv_id[:12]}... → cv={chatgpt_conv_id[:8]}... "
        f"parent={(parent_msg_id or '')[:8]}..."
    )
    return lc_conv_id


def sniff_and_save(lc_conv_id: Optional[str], chatgpt_conv_id: Optional[str],
                   parent_msg_id: Optional[str]) -> None:
    """流式响应嗅探回写。同一对话多次 chunk 触发时，最后一次 message_id 会覆盖。"""
    if not _enabled() or not lc_conv_id or not chatgpt_conv_id:
        return
    init_db()
    _upsert_mapping(lc_conv_id, chatgpt_conv_id, parent_msg_id)
