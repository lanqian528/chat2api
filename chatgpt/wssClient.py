import time

from utils.Logger import logger

wss_map = {}


async def ac2wss(access_token):
    if access_token in wss_map:
        if int(time.time()) - wss_map.get(access_token, {}).get("timestamp", 0) < 60 * 60:
            wss_map[access_token]["timestamp"] = int(time.time())
            wss_url = wss_map[access_token] = wss_map[access_token]["wss_url"]
            logger.info(f"access_token -> wss_url from cache")
            return True, wss_url
        else:
            logger.info(f"access_token -> wss_url expired")
            return True, None
    else:
        return False, None


async def set_wss(access_token, wss_url):
    wss_map[access_token] = {"timestamp": int(time.time()), "wss_url": wss_url}
    return True