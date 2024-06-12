import asyncio
import os

from fastapi import HTTPException

from chatgpt.refreshToken import rt2ac, save_refresh_map
from utils.Logger import logger
from utils.config import authorization_list

count = 0
token_list = []
error_token_list = []

DATA_FOLDER = "data"
TOKENS_FILE = os.path.join(DATA_FOLDER, "token.txt")
ERROR_TOKENS_FILE = os.path.join(DATA_FOLDER, "error_token.txt")

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

if os.path.exists(ERROR_TOKENS_FILE):
    with open(ERROR_TOKENS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                error_token_list.append(line.strip())
else:
    with open(ERROR_TOKENS_FILE, "w", encoding="utf-8") as f:
        pass

if token_list:
    logger.info(f"Token list count: {len(token_list)}")


def get_req_token(req_token):
    if req_token in authorization_list:
        if token_list:
            global count
            count += 1
            count %= len(token_list)
            while token_list[count] in error_token_list:
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
            except HTTPException:
                with open(ERROR_TOKENS_FILE, "a", encoding="utf-8") as f:
                    f.write(token + "\n")
                if token not in error_token_list:
                    error_token_list.append(token)
    logger.info("All tokens refreshed.")
