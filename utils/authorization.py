from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from utils.config import authorization

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def verify_token(token: str = Depends(oauth2_scheme)):
    if not authorization or token == authorization:
        return True
    else:
        return False
