"""harvester CLI 入口。

用法示例：
  python -m src.harvest                         # 全量（跳过已成功）
  python -m src.harvest --only a@b.com,c@d.com
  python -m src.harvest --failed
  python -m src.harvest --force
  python -m src.harvest --headless
  python -m src.harvest --export tokens.json    # 不调 chat2api，只导出
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import List, Optional

import click

from .cache import StateStore
from .chat2api_client import Chat2ApiClient
from .config import load_accounts, load_config
from .log_setup import setup_logging
from .models import Account, HarvestResult, TokenSet
from .oauth_flow import harvest_one


def _filter_accounts(
    accounts: List[Account],
    only: Optional[str],
    failed_only: bool,
    force: bool,
    state: StateStore,
) -> List[Account]:
    if only:
        wanted = {e.strip().lower() for e in only.split(",") if e.strip()}
        accounts = [a for a in accounts if a.email.lower() in wanted]
        if not accounts:
            raise click.ClickException("--only 指定的邮箱在 accounts.csv 中找不到")

    if failed_only:
        fails = set(e.lower() for e in state.list_failed())
        accounts = [a for a in accounts if a.email.lower() in fails]

    if not force:
        filtered = []
        for a in accounts:
            if state.is_banned(a.email):
                continue
            if state.is_recently_success(a.email):
                continue
            filtered.append(a)
        accounts = filtered

    return accounts


async def _run(
    only: Optional[str],
    failed_only: bool,
    force: bool,
    headless_override: bool,
    export_path: Optional[str],
) -> int:
    config = load_config()
    if headless_override:
        config.headless = True
    config.ensure_dirs()

    logger = setup_logging(config.logs_dir)
    logger.info(f"harvester 启动 base={config.chat2api_base_url} headless={config.headless}")

    all_accounts = load_accounts()
    state = StateStore(config.state_dir)
    accounts = _filter_accounts(all_accounts, only, failed_only, force, state)

    if not accounts:
        logger.info("没有需要处理的账号（全部已成功 / 已禁用）")
        return 0
    logger.info(f"共 {len(accounts)} 个账号待处理（总 {len(all_accounts)}）")

    # 模式分叉：导出 vs 写回 chat2api
    exported_tokens: List[dict] = []
    client: Optional[Chat2ApiClient] = None

    if export_path:
        async def on_success(account: Account, token_set: TokenSet) -> None:
            # 注意：rt 完整值此处会写入 JSON 文件，仅用于 --export 模式
            exported_tokens.append({
                "email": account.email,
                "note": account.note,
                "proxy_name": account.proxy_name,
                "refresh_token": token_set.refresh_token,
            })
    else:
        client = Chat2ApiClient(
            config.chat2api_base_url,
            config.chat2api_api_prefix,
            config.chat2api_admin_password,
        )
        if not await client.healthcheck():
            logger.error("chat2api 健康检查失败，中止。请先启动 chat2api 或检查 .env")
            return 2

        async def on_success(account: Account, token_set: TokenSet) -> None:
            proxy_url = ""
            if account.proxy_name:
                proxy_url = await client.resolve_proxy(account.proxy_name) or ""
                if not proxy_url:
                    logger.warning(
                        f"[{account.masked_email()}] proxy_name='{account.proxy_name}' "
                        f"在 chat2api 中未找到，将导入但不绑定代理"
                    )
            await client.import_token(
                refresh_token=token_set.refresh_token,
                note=account.note,
                proxy_name=account.proxy_name if proxy_url else "",
                proxy_url=proxy_url,
            )
            # 额外：上报给 Harvester 看板，更新 last_rt_prefix / 状态
            await client.report_harvest(
                email=account.email,
                rt_prefix=token_set.rt_prefix,
                success=True,
                imported_token=token_set.refresh_token,
            )
            logger.info(f"[{account.masked_email()}] → chat2api import OK + reported")

    # 串行执行（并行留作未来增强）
    results: List[HarvestResult] = []
    for idx, acc in enumerate(accounts, start=1):
        masked = acc.masked_email()
        logger.info(f"--- [{idx}/{len(accounts)}] {masked} ---")

        if idx > 1 and config.interval_between_accounts_seconds > 0:
            await asyncio.sleep(config.interval_between_accounts_seconds)

        attempts = max(config.retry_on_fail, 0) + 1
        last: Optional[HarvestResult] = None
        for attempt in range(1, attempts + 1):
            last = await harvest_one(acc, config, on_success=on_success)
            if last.ok:
                break
            if attempt < attempts:
                logger.warning(f"[{masked}] 第 {attempt} 次失败，将重试：{last.error[:120]}")
                await asyncio.sleep(5)

        assert last is not None
        results.append(last)

        if last.ok:
            state.mark_success(acc.email, last.rt_prefix, imported=last.imported)
        else:
            banned = any(k in (last.error or "").lower() for k in ("banned", "blocked", "suspended"))
            state.mark_failure(acc.email, last.error, banned=banned)
            # 非 export 模式下，把失败也上报给 chat2api 看板
            if client is not None:
                try:
                    await client.report_harvest(
                        email=acc.email,
                        success=False,
                        error=last.error,
                    )
                except Exception:
                    pass

    # 汇总
    ok_count = sum(1 for r in results if r.ok)
    failed_count = len(results) - ok_count
    logger.info(f"====== 完成 | 成功 {ok_count} | 失败 {failed_count} ======")
    for r in results:
        if not r.ok:
            logger.info(f"  ❌ {r.email}: {r.error[:200]}")

    if export_path and exported_tokens:
        out = Path(export_path)
        out.write_text(
            json.dumps(exported_tokens, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(f"已导出 {len(exported_tokens)} 条 rt 到 {out.resolve()}")

    return 0 if failed_count == 0 else 1


@click.command()
@click.option("--only", default=None, help="仅处理这些邮箱，英文逗号分隔")
@click.option("--failed", "failed_only", is_flag=True, help="只处理上次失败的账号")
@click.option("--force", is_flag=True, help="忽略 state，强制全量重跑")
@click.option("--headless", is_flag=True, help="覆盖 .env 的 HEADLESS=true（仅在确认无 Arkose 时用）")
@click.option("--export", "export_path", default=None, help="不调 chat2api，导出完整 rt 到 JSON 文件")
def main(only, failed_only, force, headless, export_path):
    try:
        code = asyncio.run(_run(only, failed_only, force, headless, export_path))
    except KeyboardInterrupt:
        click.echo("用户中断")
        sys.exit(130)
    sys.exit(code)


if __name__ == "__main__":
    main()
