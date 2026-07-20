"""Per-account 持久化状态：成功/失败/重试计数。"""

import hashlib
import json
import time
from pathlib import Path
from typing import Dict, Optional


def _email_hash(email: str) -> str:
    return hashlib.sha256(email.encode("utf-8")).hexdigest()[:16]


class StateStore:
    """每账号一个 json 文件，记录最近一次成功/失败信息。"""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, email: str) -> Path:
        return self.state_dir / f"{_email_hash(email)}.json"

    def get(self, email: str) -> Dict:
        p = self._path(email)
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def is_recently_success(self, email: str, within_seconds: int = 7 * 24 * 3600) -> bool:
        rec = self.get(email)
        last = rec.get("last_success_at", 0)
        return bool(last and (time.time() - last) < within_seconds)

    def mark_success(self, email: str, rt_prefix: str, imported: bool) -> None:
        now = int(time.time())
        rec = self.get(email)
        rec.update({
            "email": email,
            "last_success_at": now,
            "last_attempt_at": now,
            "last_rt_prefix": rt_prefix,
            "imported": imported,
            "last_error": "",
            "fail_count": 0,
            "banned": False,
        })
        self._write(email, rec)

    def mark_failure(self, email: str, error: str, banned: bool = False) -> None:
        now = int(time.time())
        rec = self.get(email)
        rec.update({
            "email": email,
            "last_attempt_at": now,
            "last_error": error[:300],
            "last_error_at": now,
            "fail_count": int(rec.get("fail_count", 0)) + 1,
            "banned": banned or rec.get("banned", False),
        })
        self._write(email, rec)

    def list_failed(self) -> list:
        emails = []
        for p in self.state_dir.glob("*.json"):
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if not rec.get("last_success_at") and rec.get("email"):
                emails.append(rec["email"])
        return emails

    def is_banned(self, email: str) -> bool:
        return bool(self.get(email).get("banned"))

    def _write(self, email: str, data: Dict) -> None:
        self._path(email).write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
