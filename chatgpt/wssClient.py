import json
import time

from utils.Logger import logger
import chatgpt.globals as globals


def save_wss_map(wss_map):
    with open(globals.WSS_MAP_FILE, "w") as file:
        json.dump(wss_map, file)


async def token2wss(token):
    if not token:
        return False, None
    if token in globals.wss_map:
        wss_mode = globals.wss_map[token]["wss_mode"]
        if wss_mode:
            if int(time.time()) - globals.wss_map.get(token, {}).get("timestamp", 0) < 60 * 60:
                wss_url = globals.wss_map[token]["wss_url"]
                logger.info(f"token -> wss_url from cache")
                return wss_mode, wss_url
            else:
                logger.info(f"token -> wss_url expired")
                return wss_mode, None
        else:
            return False, None
    return False, None


async def set_wss(token, wss_mode, wss_url=None):
    if not token:
        return True
    globals.wss_map[token] = {"timestamp": int(time.time()), "wss_url": wss_url, "wss_mode": wss_mode}
    save_wss_map(globals.wss_map)
    return True
