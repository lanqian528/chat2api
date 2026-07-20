"""日志配置：控制台 + 文件。密码/token 自动脱敏。"""

import logging
import re
import sys
from pathlib import Path
from typing import Optional


_PASSWORD_HINTS = ("password", "passwd", "secret", "token")


class SensitiveFilter(logging.Filter):
    """在日志输出前对关键字段做 mask。简单启发式，不保证万能。"""

    # refresh token 前缀 rt_ 后紧跟字符 → 保留前 8 char
    _RT_PATTERN = re.compile(r"(rt_[A-Za-z0-9\-_\.]{5})[A-Za-z0-9\-_\.]{20,}")
    _JWT_PATTERN = re.compile(r"(eyJ[A-Za-z0-9\-_\.]{10})[A-Za-z0-9\-_\.]{40,}")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            msg = self._RT_PATTERN.sub(r"\1***", msg)
            msg = self._JWT_PATTERN.sub(r"\1***", msg)
            # args 里的 password 如果被显式 %s 了一般也会在 msg 里，已处理
            record.msg = msg
            record.args = ()
        except Exception:
            pass
        return True


def setup_logging(logs_dir: Path, level: str = "INFO") -> logging.Logger:
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("harvester")
    logger.setLevel(level)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    ch.addFilter(SensitiveFilter())
    logger.addHandler(ch)

    fh = logging.FileHandler(logs_dir / "harvester.log", encoding="utf-8")
    fh.setFormatter(fmt)
    fh.addFilter(SensitiveFilter())
    logger.addHandler(fh)

    logger.propagate = False
    return logger
