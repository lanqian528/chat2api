import os

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from chatgpt.refreshToken import rt2ac
from utils.Logger import logger
from utils.config import authorization_list

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

count = 0
token_list = []

DATA_FOLDER = "data"
TOKENS_FILE = os.path.join(DATA_FOLDER, "token.txt")
if not os.path.exists(DATA_FOLDER):
    os.makedirs(DATA_FOLDER)

if os.path.exists("data/token.txt"):
    with open("data/token.txt", "r", encoding="utf-8") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                token_list.append(line.strip())
else:
    with open("data/token.txt", "w", encoding="utf-8") as f:
        pass
if token_list:
    logger.info(f"Token list count: {len(token_list)}")


async def verify_token(req_token: str = Depends(oauth2_scheme)):
    if not req_token:
        if authorization_list:
            logger.error("Unauthorized access token")
            raise HTTPException(status_code=401)
        else:
            return None
    else:
        if authorization_list:
            if req_token in authorization_list:
                if token_list:
                    global count
                    count += 1
                    count %= len(token_list)
                    return await verify_token(token_list[count])
                else:
                    return None
            else:
                if req_token.startswith("eyJhbGciOi") or req_token.startswith("fk-"):
                    access_token = req_token
                    return access_token
                elif len(req_token) == 45:
                    try:
                        access_token = await rt2ac(req_token)
                        return access_token
                    except HTTPException as e:
                        logger.error(f"Unauthorized :access token {req_token}")
                        raise HTTPException(status_code=e.status_code, detail=e.detail)
                else:
                    return req_token
        else:
            return req_token
