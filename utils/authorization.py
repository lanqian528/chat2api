from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from utils.config import authorization_list

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def verify_token(token: str = Depends(oauth2_scheme)):
    if not authorization_list or token in authorization_list:
        return token
    elif token.startswith("eyJhbGciOi"):
        return token
    else:
        return False
