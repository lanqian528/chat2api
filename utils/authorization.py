import asyncio
import os

from fastapi import HTTPException

from chatgpt.refreshToken import rt2ac, save_refresh_map
from utils.Logger import logger
from utils.config import authorization_list
from utils.config import enable_refresh_rt
from utils.rt2at import start_refresh_sheduler

count = 0
token_list = []

DATA_FOLDER = "data"
TOKENS_FILE = os.path.join(DATA_FOLDER, "token.txt")
RT_FILE = os.path.join(DATA_FOLDER, "refresh_token.txt")

if not os.path.exists(DATA_FOLDER):
    os.makedirs(DATA_FOLDER)

if os.path.exists(TOKENS_FILE):
    with open(TOKENS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                token_list.append(line.strip())
else:
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        pass

if token_list:
    logger.info(f"Token list count: {len(token_list)}")

if enable_refresh_rt:
    start_refresh_sheduler(token_list,RT_FILE, TOKENS_FILE)

def get_req_token(req_token):
    if req_token in authorization_list:
        if token_list:
            global count
            count += 1
            count %= len(token_list)
            return token_list[count]
        else:
            return None
    else:
        return req_token


async def verify_token(req_token):
    if not req_token:
        if authorization_list:
            logger.error("Unauthorized with empty token.")
            raise HTTPException(status_code=401)
        else:
            return None
    else:
        if req_token.startswith("eyJhbGciOi") or req_token.startswith("fk-"):
            access_token = req_token
            return access_token
        elif len(req_token) == 45:
            try:
                access_token = await rt2ac(req_token, force_refresh=False)
                return access_token
            except HTTPException as e:
                logger.error(f"{e.detail}: {req_token}")
                raise HTTPException(status_code=e.status_code, detail=e.detail)
        else:
            return req_token


async def refresh_all_tokens(force_refresh=False):
    for token in token_list:
        if len(token) == 45:
            try:
                await asyncio.sleep(2)
                await rt2ac(token, force_refresh=force_refresh)
            except HTTPException as e:
                logger.error(f"{e.detail}: {token}")
                raise HTTPException(status_code=e.status_code, detail=e.detail)
    logger.info("All tokens refreshed.")
