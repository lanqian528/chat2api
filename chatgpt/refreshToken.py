import hashlib
import json
import random
import time

from fastapi import HTTPException

from utils.Client import Client
from utils.Logger import logger
from utils.configs import proxy_url_list
import utils.globals as globals


async def rt2ac(refresh_token, force_refresh=False):
    if not force_refresh and (refresh_token in globals.refresh_map and int(time.time()) - globals.refresh_map.get(refresh_token, {}).get("timestamp", 0) < 5 * 24 * 60 * 60):
        access_token = globals.refresh_map[refresh_token]["token"]
        # logger.info(f"refresh_token -> access_token from cache")
        return access_token
    else:
        try:
            access_token = await chat_refresh(refresh_token)
            globals.refresh_map[refresh_token] = {"token": access_token, "timestamp": int(time.time())}
            with open(globals.REFRESH_MAP_FILE, "w") as f:
                json.dump(globals.refresh_map, f, indent=4)
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
    headers = {
        'accept': '*/*',
        'accept-encoding': 'gzip, deflate, br, zstd',
        'accept-language': 'en-US,en;q=0.9',
        'content-type': 'application/json',
        'origin': 'https://auth0.openai.com',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0'
    }
    session_id = hashlib.md5(refresh_token.encode()).hexdigest()
    proxy_url = random.choice(proxy_url_list).replace("{}", session_id) if proxy_url_list else None
    client = Client(proxy=proxy_url)
    try:
        r = await client.post("https://auth0.openai.com/oauth/token", json=data, headers=headers, timeout=15)
        if r.status_code == 200:
            access_token = r.json()['access_token']
            return access_token
        else:
            if "invalid_grant" in r.text or "access_denied" in r.text:
                if refresh_token not in globals.error_token_list:
                    globals.error_token_list.append(refresh_token)
                    with open(globals.ERROR_TOKENS_FILE, "a", encoding="utf-8") as f:
                        f.write(refresh_token + "\n")
                raise Exception(r.text)
            else:
                raise Exception(r.text[:300])
    except Exception as e:
        logger.error(f"Failed to refresh access_token `{refresh_token}`: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to refresh access_token.")
    finally:
        await client.close()
        del client
