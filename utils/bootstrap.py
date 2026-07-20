from utils.Logger import logger
from utils.configs import (
    init_apply_on_empty,
    init_force,
    init_group_size,
    init_proxies,
    init_tokens,
)
import utils.globals as globals
from utils.routing import build_group_assignments, save_routing_config, sync_bindings_to_fp


def _split_items(raw):
    if not raw:
        return []
    if "\n" in raw:
        parts = raw.splitlines()
    else:
        parts = raw.split(",")
    items = []
    for part in parts:
        item = part.strip()
        if item:
            items.append(item)
    return items


def _parse_proxies(raw):
    proxies = []
    for index, item in enumerate(_split_items(raw), start=1):
        if "|" in item:
            name, proxy_url = item.split("|", 1)
            name = name.strip() or f"IP-{index}"
            proxy_url = proxy_url.strip()
        else:
            name = f"IP-{index}"
            proxy_url = item
        if proxy_url:
            proxies.append({"name": name, "proxy_url": proxy_url})
    return proxies


def initialize_tokens():
    tokens = _split_items(init_tokens)
    if not tokens:
        return False
    has_existing = bool(globals.token_list)
    if has_existing and init_apply_on_empty and not init_force:
        logger.info("Bootstrap tokens skipped: token.txt already populated")
        return False

    seen = set()
    normalized = []
    for token in tokens:
        if token not in seen:
            normalized.append(token)
            seen.add(token)

    globals.token_list[:] = normalized
    with open(globals.TOKENS_FILE, "w", encoding="utf-8") as f:
        for token in normalized:
            f.write(token + "\n")
    logger.info(f"Bootstrap tokens initialized: {len(normalized)} accounts")
    return True


def initialize_routing():
    proxies = _parse_proxies(init_proxies)
    if not proxies:
        return False
    if not globals.token_list:
        logger.info("Bootstrap routing skipped: no tokens available")
        return False

    has_existing = bool(globals.routing_config.get("bindings"))
    if has_existing and init_apply_on_empty and not init_force:
        logger.info("Bootstrap routing skipped: routing_config.json already populated")
        return False

    result = build_group_assignments(list(globals.token_list), proxies, init_group_size)
    save_routing_config(result)
    sync_bindings_to_fp(result["bindings"])
    logger.info(
        f"Bootstrap routing initialized: {len(result['proxies'])} proxies, "
        f"{len(result['bindings'])} bindings, group size {init_group_size}"
    )
    return True


def initialize_from_env():
    changed_tokens = initialize_tokens()
    changed_routing = initialize_routing()
    return changed_tokens or changed_routing
