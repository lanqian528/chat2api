"""代理 IP 地域一致性查询与缓存。

策略：
  1. 从 proxy_url 解析 host；
  2. 查询 _GEO_DEFAULTS（手工配置的主流地区表）作为回退；
  3. 若 IP_GEO_PROVIDER=ip-api 且允许联网，通过 ip-api.com/json/{ip} 查询；
     失败/超时即用回退表，不阻塞请求；
  4. 结果缓存到 data/antiban_geo.json，TTL=IP_GEO_CACHE_TTL_DAYS。

输出结构：
  {
    "country": "JP",
    "timezone": "Asia/Tokyo",
    "tz_offset_min": 540,
    "accept_language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
    "oai_language": "ja-JP",
    "_ts": <unix ts>
  }
"""

import json
import re
import socket
import threading
import time
from typing import Dict, Optional
from urllib import request as urllib_request
from urllib.error import URLError

import utils.globals as globals
from utils import configs
from utils.Logger import logger

_write_lock = threading.Lock()

_GEO_DEFAULTS = {
    "US": ("en-US,en;q=0.9", "en-US", -480, "America/Los_Angeles"),
    "JP": ("ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7", "ja-JP", 540, "Asia/Tokyo"),
    "SG": ("en-SG,en;q=0.9,zh-CN;q=0.7,zh;q=0.6", "en-SG", 480, "Asia/Singapore"),
    "HK": ("zh-HK,zh;q=0.9,en;q=0.8", "zh-HK", 480, "Asia/Hong_Kong"),
    "TW": ("zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7", "zh-TW", 480, "Asia/Taipei"),
    "KR": ("ko-KR,ko;q=0.9,en;q=0.7", "ko-KR", 540, "Asia/Seoul"),
    "DE": ("de-DE,de;q=0.9,en;q=0.7", "de-DE", 60, "Europe/Berlin"),
    "GB": ("en-GB,en;q=0.9", "en-GB", 0, "Europe/London"),
    "CA": ("en-CA,en;q=0.9,fr-CA;q=0.7", "en-CA", -300, "America/Toronto"),
    "FR": ("fr-FR,fr;q=0.9,en;q=0.7", "fr-FR", 60, "Europe/Paris"),
    "AU": ("en-AU,en;q=0.9", "en-AU", 600, "Australia/Sydney"),
}


def _extract_host(proxy_url: str) -> Optional[str]:
    if not proxy_url:
        return None
    m = re.match(r"^(?:https?|socks5h?)://(?:[^@]+@)?([^:/?#]+)", proxy_url, re.I)
    return m.group(1) if m else None


def _resolve_host(host: str) -> Optional[str]:
    try:
        return socket.gethostbyname(host)
    except OSError:
        return None


def _persist() -> None:
    with _write_lock:
        with open(globals.ANTIBAN_GEO_FILE, "w", encoding="utf-8") as f:
            json.dump(globals.antiban_geo_cache, f, indent=2, ensure_ascii=False)


def _build_geo_from_country(country: str) -> Dict:
    row = _GEO_DEFAULTS.get(country.upper())
    if not row:
        return {
            "country": country.upper(),
            "timezone": configs.client_timezone,
            "tz_offset_min": configs.client_timezone_offset_min,
            "accept_language": configs.accept_language,
            "oai_language": configs.oai_language,
        }
    return {
        "country": country.upper(),
        "accept_language": row[0],
        "oai_language": row[1],
        "tz_offset_min": row[2],
        "timezone": row[3],
    }


def _query_ip_api(ip: str, timeout: int = 3) -> Optional[str]:
    """返回 country code，失败返回 None。不走代理，查询本机看到的 IP。"""
    try:
        url = f"http://ip-api.com/json/{ip}?fields=status,countryCode"
        with urllib_request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") == "success":
                return data.get("countryCode")
    except (URLError, socket.timeout, json.JSONDecodeError) as e:
        logger.info(f"[antiban] ip-api query failed for {ip}: {e}")
    except Exception as e:  # pragma: no cover
        logger.warning(f"[antiban] ip-api unexpected error: {e}")
    return None


def get_geo(proxy_url: Optional[str]) -> Optional[Dict]:
    if not configs.enable_antiban or not proxy_url:
        return None

    host = _extract_host(proxy_url)
    if not host:
        return None

    cache = globals.antiban_geo_cache
    ttl = configs.ip_geo_cache_ttl_days * 86400
    cached = cache.get(host)
    if cached and time.time() - cached.get("_ts", 0) < ttl:
        return cached

    ip = _resolve_host(host)
    if not ip:
        return None

    country = _query_ip_api(ip) if configs.ip_geo_provider == "ip-api" else None
    if not country:
        return None

    geo_info = _build_geo_from_country(country)
    geo_info["_ts"] = int(time.time())
    cache[host] = geo_info
    try:
        _persist()
    except Exception as e:  # pragma: no cover
        logger.error(f"[antiban] geo persist failed: {e}")
    logger.info(f"[antiban] geo resolved {host} → {country}")
    return geo_info
