"""D4: 客户端版本启动时自检。

策略：
  1. 启动时 GET https://chatgpt.com/，从 HTML 中提取 data-build 属性；
  2. 与本地 configs.oai_client_version / oai_client_build_number 比对；
  3. 偏差大（前缀完全不同 或 build 号差距 > 阈值）→ 日志告警，
     提示用户手工同步避免"客户端版本过旧"风控。

不强制更新，仅告警，避免影响主流程。
"""

import re
from typing import Optional, Tuple

from utils import configs
from utils.Logger import logger

# 启动时使用的最小请求超时（避免阻塞）
_PROBE_TIMEOUT = 5

# build number 偏差阈值：超过则告警
_BUILD_NUMBER_GAP_THRESHOLD = 200_000


def _extract_data_build(html: str) -> Optional[str]:
    """从 HTML 中解析 <html data-build="prod-xxxx"> 字符串。"""
    m = re.search(r'<html[^>]*data-build="([^"]+)"', html)
    return m.group(1) if m else None


def _extract_build_number(html: str) -> Optional[int]:
    """从 ChatGPT HTML 中解析 buildNumber（嵌入在 __NEXT_DATA__ 或 script 中）。"""
    # buildNumber 通常出现在 _buildManifest.js 或全局变量中；做宽匹配
    m = re.search(r'"buildNumber"\s*:\s*(\d+)', html)
    return int(m.group(1)) if m else None


def _build_prefix(version: str) -> str:
    """提取 build 字符串的"前缀稳定段"用于粗比对。

    例: "prod-f501fe933b3edf57aea882da888e1a544df99840" → "prod"
    """
    if not version:
        return ""
    if "-" in version:
        return version.split("-", 1)[0]
    return version[:8]


async def probe_and_compare() -> Tuple[bool, str]:
    """探测官网 data-build，与本地配置比对。

    返回 (is_drift, message)：
      is_drift=True 表示偏差大，已发告警；False 表示同步或网络不可达（跳过告警）。
    """
    import httpx
    local_version = configs.oai_client_version or ""
    local_build_num = configs.oai_client_build_number

    base_urls = configs.chatgpt_base_url_list or ["https://chatgpt.com"]
    target = (base_urls[0] if isinstance(base_urls, list) else base_urls).rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT, follow_redirects=False) as client:
            resp = await client.get(target + "/", headers={
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "accept-language": configs.accept_language or "en-US,en;q=0.9",
                "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            })
    except Exception as e:
        # 启动期网络问题不阻断主流程，仅 info 级日志
        logger.info(f"[antiban] version_check skipped (network: {e})")
        return False, "skipped"

    if resp.status_code >= 400:
        logger.info(f"[antiban] version_check skipped (status {resp.status_code})")
        return False, "skipped"

    remote_build = _extract_data_build(resp.text)
    remote_build_num = _extract_build_number(resp.text)

    if not remote_build:
        logger.info("[antiban] version_check: data-build not found in HTML; sentinel may have changed")
        return False, "no-build"

    # 比对 1: 前缀（prod- / dev- 等）
    if _build_prefix(local_version) != _build_prefix(remote_build):
        msg = (
            f"oai-client-version prefix mismatch: local={local_version[:30]}... "
            f"remote={remote_build[:30]}..."
        )
        logger.warning(f"[antiban] version_check DRIFT: {msg}")
        return True, msg

    # 比对 2: build number 偏差
    if remote_build_num and local_build_num:
        try:
            gap = abs(int(remote_build_num) - int(local_build_num))
            if gap > _BUILD_NUMBER_GAP_THRESHOLD:
                msg = (
                    f"oai-client-build-number gap={gap} exceeds "
                    f"threshold={_BUILD_NUMBER_GAP_THRESHOLD}; consider updating configs.py "
                    f"(local={local_build_num} remote={remote_build_num})"
                )
                logger.warning(f"[antiban] version_check DRIFT: {msg}")
                return True, msg
        except (TypeError, ValueError):
            pass

    logger.info(
        f"[antiban] version_check OK: local={_build_prefix(local_version)}... "
        f"remote build_num={remote_build_num}"
    )
    return False, "in-sync"
