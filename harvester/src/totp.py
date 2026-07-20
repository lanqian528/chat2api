"""TOTP 2FA：由 pyotp 封装。"""

import pyotp


def current_code(secret: str) -> str:
    """根据 base32 secret 生成当前 6 位 TOTP 码。"""
    clean = (secret or "").replace(" ", "").upper()
    if not clean:
        raise ValueError("TOTP secret is empty")
    return pyotp.TOTP(clean).now()


def is_valid_secret(secret: str) -> bool:
    try:
        current_code(secret)
        return True
    except Exception:
        return False
