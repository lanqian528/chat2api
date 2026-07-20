"""Antiban 对外统一入口（PR-1 骨架：不拦截不改动，仅日志）。

后续 PR 按顺序充实：
  PR-2 bucket 粘性
  PR-3 cooldown/geo
  PR-4 circuit 报错上报
  PR-5 fingerprint 扩展
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from utils import configs
from utils.antiban import account_risk, bucket, circuit, cooldown, fingerprint, geo
from utils.Logger import logger


@dataclass
class AntibanContext:
    token: str = ""
    bucket_id: Optional[str] = None
    proxy_url: Optional[str] = None
    header_overrides: Dict[str, str] = field(default_factory=dict)
    tz_offset_min: Optional[int] = None
    fp_overrides: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = False


async def init() -> None:
    """应用启动时调用。PR-1 骨架仅打印开关状态。"""
    if not configs.enable_antiban:
        logger.info("[antiban] disabled; original behavior preserved")
        return

    # 冷启动：把已加载 tokens 批量分配到桶（已绑定则跳过）
    try:
        import utils.globals as _globals  # 避免循环
        bucket.bulk_assign(list(_globals.token_list))
    except Exception as e:
        logger.error(f"[antiban] bulk_assign on startup failed: {e}")

    stats = bucket.get_bucket_stats()
    logger.info(
        f"[antiban] enabled | buckets={stats['bucket_count']} "
        f"accounts={stats['account_total']} healthy={stats['healthy']} degraded={stats.get('degraded', 0)}"
    )

    # D4: 后台异步探测 oai-client-version 是否过旧（不阻塞启动）
    try:
        import asyncio
        from utils.antiban import version_check
        asyncio.create_task(version_check.probe_and_compare())
    except Exception as e:
        logger.info(f"[antiban] version_check schedule failed: {e}")


async def acquire_context(req_token: Optional[str]) -> AntibanContext:
    """在 ChatService.initialize_request_context() 中调用。

    PR-1 骨架：返回空 context，不改变现有行为。
    """
    ctx = AntibanContext(token=req_token or "", enabled=configs.enable_antiban)
    if not configs.enable_antiban:
        return ctx

    # 已绑定即复用；未绑定暂不分配（PR-2 实现）
    ctx.bucket_id = bucket.assign_account(ctx.token)
    ctx.proxy_url = bucket.get_bucket_proxy(ctx.token)

    # 冷却放行检查（PR-3 真正生效）
    await cooldown.wait_or_skip(ctx.token)

    # 熔断检查
    if not circuit.is_bucket_allowed(ctx.bucket_id):
        logger.warning(f"[antiban] bucket {ctx.bucket_id} still degraded")

    # 地域头（若未查到则保持默认）
    geo_info = geo.get_geo(ctx.proxy_url)
    if geo_info:
        ctx.header_overrides = {
            "accept-language": geo_info.get("accept_language", ""),
            "oai-language": geo_info.get("oai_language", ""),
            "_timezone_name": geo_info.get("timezone", ""),  # 非 header，仅透传给 chat_request
        }
        ctx.tz_offset_min = geo_info.get("tz_offset_min")

    # 指纹扩展（PR-5：按 token 维度补齐 screen/cores/device_memory，并返回拷贝）
    fp = fingerprint.ensure_extended(ctx.token)
    if fp:
        ctx.fp_overrides = fp

    return ctx


async def report_error(ctx: AntibanContext, status_code: int, detail: Any = None) -> None:
    if not ctx.enabled:
        return
    circuit.handle_response_error(ctx.token, ctx.bucket_id, status_code, detail)


async def report_network_error(ctx: AntibanContext, error_kind: str = "") -> None:
    """M3: transport 层失败（ConnectionError/超时/DNS）→ 累计后降级桶。"""
    if not ctx.enabled:
        return
    circuit.handle_network_error(ctx.token, ctx.bucket_id, error_kind)


async def report_success(ctx: AntibanContext) -> None:
    if not ctx.enabled:
        return
    cooldown.record_request(ctx.token)
    circuit.handle_response_success(ctx.token)
    circuit.reset_network_errors(ctx.bucket_id)
    bucket.mark_used(ctx.token)


def sniff_account_warning(ctx: AntibanContext, message: dict, raw_chunk: dict = None) -> None:
    """流式响应中的账号风险嗅探（Step A：仅记录，不联动 cooldown/dead）。

    调用方：chatgpt/chatFormat.py 的 stream_response，在 system 角色 continue 之前。
    设计为同步非阻塞，任何异常都吞掉，确保不影响主流程。
    """
    if not ctx or not ctx.enabled:
        return
    account_risk.sniff(ctx.token, message or {}, raw_chunk or {})
