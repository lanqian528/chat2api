from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from chatgpt.refreshToken import rt2ac
from utils.config import authorization_list

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


async def verify_token(token: str = Depends(oauth2_scheme)):
    if token and token.startswith("eyJhbGciOi"):
        return token
    elif token and len(token) == 45:
        return await rt2ac(token)
    elif not authorization_list:
        return token
    elif token and token in authorization_list:
        return token
    else:
        raise HTTPException(status_code=401, detail="Not authenticated")
