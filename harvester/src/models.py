"""数据模型。"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Account:
    email: str
    password: str
    totp_secret: str = ""
    note: str = ""
    proxy_name: str = ""

    def masked_email(self) -> str:
        local, _, domain = self.email.partition("@")
        if len(local) <= 2:
            return f"{local[0]}*@{domain}"
        return f"{local[0]}***{local[-1]}@{domain}"


@dataclass
class TokenSet:
    """Auth0 /oauth/token 返回的 token 集合。"""
    access_token: str
    refresh_token: str
    id_token: str = ""
    expires_in: int = 0
    token_type: str = "Bearer"
    scope: str = ""

    @property
    def rt_prefix(self) -> str:
        return self.refresh_token[:8] if self.refresh_token else ""


@dataclass
class HarvestResult:
    email: str
    ok: bool
    rt_prefix: str = ""
    error: str = ""
    imported: bool = False  # 是否已写入 chat2api

    @classmethod
    def success(cls, email: str, token_set: TokenSet, imported: bool = False) -> "HarvestResult":
        return cls(email=email, ok=True, rt_prefix=token_set.rt_prefix, imported=imported)

    @classmethod
    def failure(cls, email: str, error: str) -> "HarvestResult":
        return cls(email=email, ok=False, error=error[:300])
