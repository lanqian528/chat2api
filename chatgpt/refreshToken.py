import json
import os
import random
import time

from fastapi import HTTPException

from utils.Client import Client
from utils.Logger import logger
from utils.config import proxy_url_list

DATA_FOLDER = "data"
REFRESH_MAP_FILE = os.path.join(DATA_FOLDER, "refresh_map.json")

if not os.path.exists(DATA_FOLDER):
    os.makedirs(DATA_FOLDER)

if os.path.exists(REFRESH_MAP_FILE):
    with open(REFRESH_MAP_FILE, "r") as file:
        refresh_map = json.load(file)
else:
    refresh_map = {}


def save_refresh_map(refresh_map):
    with open(REFRESH_MAP_FILE, "w") as file:
        json.dump(refresh_map, file)


async def rt2ac(refresh_token, force_refresh=False):
    if not force_refresh and (refresh_token in refresh_map and int(time.time()) - refresh_map.get(refresh_token, {}).get("timestamp", 0) < 5 * 24 * 60 * 60):
        access_token = refresh_map[refresh_token]["token"]
        logger.info(f"refresh_token -> access_token from cache")
        return access_token
    else:
        try:
            access_token = await chat_refresh(refresh_token)
            refresh_map[refresh_token] = {"token": access_token, "timestamp": int(time.time())}
            save_refresh_map(refresh_map)
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
            raise Exception(r.text[:100])
    except Exception as e:
        logger.error(f"Failed to refresh access_token `{refresh_token}`: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to refresh access_token.")
    finally:
        await client.close()
        del client
