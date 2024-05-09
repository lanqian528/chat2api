from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from chatgpt.refreshToken import rt2ac, fk2sd
from utils.config import authorization_list

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


async def verify_token(token: str = Depends(oauth2_scheme)):
    if token and token.startswith("eyJhbGciOi"):
        return token
    elif token and token.startswith("fk-"):
        try:
            await fk2sd(token)
            return token
        except HTTPException as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail)
    elif token and len(token) == 45:
        try:
            access_token = await rt2ac(token)
            return access_token
        except HTTPException as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail)
    elif not authorization_list:
        return token
    elif token and token in authorization_list:
        return token
    else:
        raise HTTPException(status_code=401)
