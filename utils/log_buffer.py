"""日志环形缓冲：内存保存最近 N 条日志，供管理后台 UI 读取。

设计要点：
  - 线程安全（logging 从多个线程/协程写入）
  - 每条日志带递增 id，方便前端轮询增量获取（since_id）
  - 不替代 stdout 输出，仅附加一份内存副本
  - 缓冲区大小可配（LOG_BUFFER_SIZE，默认 2000）
"""

import io
import logging
import os
import re
import threading
import time
from collections import deque
from typing import Dict, Iterable, List, Optional


_DEFAULT_SIZE = int(os.getenv("LOG_BUFFER_SIZE", 2000))
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text or "")


class RingBufferHandler(logging.Handler):
    """线程安全的环形缓冲 handler。"""

    def __init__(self, capacity: int = _DEFAULT_SIZE):
        super().__init__(level=logging.DEBUG)
        self._buf: deque = deque(maxlen=max(int(capacity), 100))
        self._lock = threading.Lock()
        self._seq = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            raw_msg = record.getMessage()
            # 去除项目 Logger 中混入的 ANSI 颜色码，避免 UI 显示乱码
            clean_msg = _strip_ansi(raw_msg).strip("\n\r\t ")
            item = {
                "ts": record.created,
                "level": record.levelname,
                "logger": record.name,
                "msg": clean_msg,
            }
            with self._lock:
                self._seq += 1
                item["id"] = self._seq
                self._buf.append(item)
        except Exception:  # pragma: no cover
            # logging 内部出错不得反过来影响业务
            self.handleError(record)

    def snapshot(
        self,
        since_id: Optional[int] = None,
        level: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict]:
        with self._lock:
            items = list(self._buf)

        if since_id is not None:
            items = [x for x in items if x["id"] > since_id]

        if level:
            level_up = level.upper()
            if level_up != "ALL":
                # 级别层级：DEBUG < INFO < WARNING < ERROR < CRITICAL
                threshold = logging.getLevelName(level_up)
                if isinstance(threshold, int):
                    items = [
                        x for x in items
                        if logging.getLevelName(x["level"]) >= threshold
                    ]

        if keyword:
            k = keyword.lower()
            items = [x for x in items if k in x["msg"].lower()]

        if limit and limit > 0:
            items = items[-int(limit):]

        return items

    def snapshot_all(self) -> List[Dict]:
        """一键下载全部时使用，不走筛选。"""
        with self._lock:
            return list(self._buf)

    @property
    def latest_id(self) -> int:
        with self._lock:
            return self._seq

    @property
    def capacity(self) -> int:
        return self._buf.maxlen or 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)


def render_plaintext(records: Iterable[Dict]) -> str:
    """把 records 渲染为可下载的纯文本。"""
    buf = io.StringIO()
    for rec in records:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(rec.get("ts", 0)))
        buf.write(f"{ts} | {rec.get('level','INFO'):<8} | {rec.get('msg','')}\n")
    return buf.getvalue()


# 全局单例，Logger 注册、admin 路由、外部诊断都用同一个
log_buffer = RingBufferHandler()
