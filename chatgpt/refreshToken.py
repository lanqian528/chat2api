import json
import random
import time

from fastapi import HTTPException

from utils.Client import Client
from utils.Logger import logger
from utils.config import proxy_url_list
import chatgpt.globals as globals


def save_refresh_map(refresh_map):
    with open(globals.REFRESH_MAP_FILE, "w") as file:
        json.dump(refresh_map, file)


async def rt2ac(refresh_token, force_refresh=False):
    if not force_refresh and (refresh_token in globals.refresh_map and int(time.time()) - globals.refresh_map.get(refresh_token, {}).get("timestamp", 0) < 5 * 24 * 60 * 60):
        access_token = globals.refresh_map[refresh_token]["token"]
        logger.info(f"refresh_token -> access_token from cache")
        return access_token
    else:
        try:
            access_token = await chat_refresh(refresh_token)
            globals.refresh_map[refresh_token] = {"token": access_token, "timestamp": int(time.time())}
            save_refresh_map(globals.refresh_map)
            logger.info(f"refresh_token -> access_token with openai: {access_token}")
            return access_token
        except HTTPException as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail)


async def chat_refresh(refresh_token):
    data = {
        "client_id": "pdlLIX2Y72MIl2rhLhTE9VV9bN905kBh",
        "grant_type": "refresh_token",
        "redirect_uri": "com.openai.chat://auth0.openai.com/ios/com.openai.chat/callback",
        "refresh_token": refresh_token
    }
    client = Client(proxy=random.choice(proxy_url_list) if proxy_url_list else None)
    try:
        r = await client.post("https://auth0.openai.com/oauth/token", json=data, timeout=5)
        if r.status_code == 200:
            access_token = r.json()['access_token']
            return access_token
        else:
            with open(globals.ERROR_TOKENS_FILE, "a", encoding="utf-8") as f:
                f.write(refresh_token + "\n")
            if refresh_token not in globals.error_token_list:
                globals.error_token_list.append(refresh_token)
            raise Exception(r.text[:100])
    except Exception as e:
        logger.error(f"Failed to refresh access_token `{refresh_token}`: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to refresh access_token.")
    finally:
        await client.close()
        del client
