import json
import os
import time

from utils.Logger import logger

DATA_FOLDER = "data"
WSS_MAP_FILE = os.path.join(DATA_FOLDER, "wss_map.json")

wss_map = {}

if not os.path.exists(DATA_FOLDER):
    os.makedirs(DATA_FOLDER)

if os.path.exists(WSS_MAP_FILE):
    with open(WSS_MAP_FILE, "r") as file:
        wss_map = json.load(file)
else:
    wss_map = {}


def save_wss_map(wss_map):
    with open(WSS_MAP_FILE, "w") as file:
        json.dump(wss_map, file)


async def token2wss(token):
    if not token:
        return False, None
    if token in wss_map:
        wss_mode = wss_map[token]["wss_mode"]
        if wss_mode:
            if int(time.time()) - wss_map.get(token, {}).get("timestamp", 0) < 60 * 60:
                wss_url = wss_map[token]["wss_url"]
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
    wss_map[token] = {"timestamp": int(time.time()), "wss_url": wss_url, "wss_mode": wss_mode}
    save_wss_map(wss_map)
    return True
