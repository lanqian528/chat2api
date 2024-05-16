import random
import time

from fastapi import HTTPException

from utils.Client import Client
from utils.Logger import logger
from utils.config import proxy_url_list

refresh_map = {}
fake_map = {}


async def rt2ac(refresh_token):
    if refresh_token in refresh_map and int(time.time()) - refresh_map.get(refresh_token, {}).get("timestamp", 0) < 24 * 60 * 60:
        access_token = refresh_map[refresh_token]["token"]
        logger.info(f"refresh_token -> access_token from cache")
        return access_token
    else:
        access_token = await chat_refresh(refresh_token)
        refresh_map[refresh_token] = {"token": access_token, "timestamp": int(time.time())}
        logger.info(f"refresh_token -> access_token with openai: {access_token}")
        return access_token


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
            raise Exception("Unknown or invalid refresh token.")
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))
    finally:
        await client.close()
        del client
