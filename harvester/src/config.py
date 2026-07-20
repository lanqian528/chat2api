"""配置加载：.env + accounts.csv。"""

import csv
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

from .models import Account


def _here() -> Path:
    return Path(__file__).resolve().parent.parent


@dataclass
class Config:
    # chat2api
    chat2api_base_url: str
    chat2api_api_prefix: str
    chat2api_admin_password: str

    # Playwright / 行为
    headless: bool = False
    pause_for_arkose_seconds: int = 90
    timeout_per_account_seconds: int = 180
    parallel: int = 1
    retry_on_fail: int = 1
    interval_between_accounts_seconds: int = 30
    playwright_proxy: Optional[str] = None

    # OAuth
    oauth_client_id: str = "pdlLIX2Y72MIl2rhLhTE9VV9bN905kBh"
    oauth_redirect_uri: str = "com.openai.chat://auth0.openai.com/ios/com.openai.chat/callback"
    oauth_audience: str = "https://api.openai.com/v1"
    oauth_scope: str = (
        "openai email profile offline_access model.request model.read "
        "organization.read organization.write"
    )

    # 路径
    root_dir: Path = field(default_factory=_here)

    @property
    def profiles_dir(self) -> Path:
        return self.root_dir / "profiles"

    @property
    def state_dir(self) -> Path:
        return self.root_dir / "state"

    @property
    def logs_dir(self) -> Path:
        return self.root_dir / "logs"

    def ensure_dirs(self) -> None:
        for d in (self.profiles_dir, self.state_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)


def _is_true(val: str) -> bool:
    return (val or "").strip().lower() in ("true", "1", "yes", "y", "t")


def load_config(env_path: Optional[Path] = None) -> Config:
    root = _here()
    load_dotenv(dotenv_path=env_path or (root / ".env"))

    base_url = os.getenv("CHAT2API_BASE_URL", "").strip()
    api_prefix = os.getenv("CHAT2API_API_PREFIX", "").strip()
    admin_pwd = os.getenv("CHAT2API_ADMIN_PASSWORD", "").strip()

    if not base_url or not admin_pwd:
        raise RuntimeError(
            "缺少必要环境变量：请在 harvester/.env 里配置 "
            "CHAT2API_BASE_URL + CHAT2API_ADMIN_PASSWORD。"
        )

    scope_default = (
        "openid email profile offline_access model.request model.read "
        "organization.read organization.write"
    )

    return Config(
        chat2api_base_url=base_url,
        chat2api_api_prefix=api_prefix,
        chat2api_admin_password=admin_pwd,
        headless=_is_true(os.getenv("HEADLESS", "false")),
        pause_for_arkose_seconds=int(os.getenv("PAUSE_FOR_ARKOSE_SECONDS", "90")),
        timeout_per_account_seconds=int(os.getenv("TIMEOUT_PER_ACCOUNT_SECONDS", "180")),
        parallel=int(os.getenv("PARALLEL", "1")),
        retry_on_fail=int(os.getenv("RETRY_ON_FAIL", "1")),
        interval_between_accounts_seconds=int(os.getenv("INTERVAL_BETWEEN_ACCOUNTS_SECONDS", "30")),
        playwright_proxy=os.getenv("PLAYWRIGHT_PROXY", "").strip() or None,
        oauth_client_id=os.getenv("OAUTH_CLIENT_ID", "pdlLIX2Y72MIl2rhLhTE9VV9bN905kBh").strip(),
        oauth_redirect_uri=os.getenv(
            "OAUTH_REDIRECT_URI",
            "com.openai.chat://auth0.openai.com/ios/com.openai.chat/callback",
        ).strip(),
        oauth_audience=os.getenv("OAUTH_AUDIENCE", "https://api.openai.com/v1").strip(),
        oauth_scope=os.getenv("OAUTH_SCOPE", scope_default).strip(),
        root_dir=root,
    )


def load_accounts(csv_path: Optional[Path] = None) -> List[Account]:
    path = csv_path or (_here() / "accounts.csv")
    if not path.exists():
        raise FileNotFoundError(f"账号文件不存在: {path}；请参照 accounts.csv.example 创建。")

    accounts: List[Account] = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"email", "password"}
        missing = required - set(h.strip().lower() for h in (reader.fieldnames or []))
        if missing:
            raise RuntimeError(f"accounts.csv 缺少必填列: {sorted(missing)}")
        for row in reader:
            email = (row.get("email") or "").strip()
            password = (row.get("password") or "").strip()
            if not email or not password:
                continue
            accounts.append(
                Account(
                    email=email,
                    password=password,
                    totp_secret=(row.get("totp_secret") or "").strip(),
                    note=(row.get("note") or "").strip(),
                    proxy_name=(row.get("proxy_name") or "").strip(),
                )
            )
    if not accounts:
        raise RuntimeError(f"accounts.csv 为空或所有行缺失 email/password")
    return accounts
