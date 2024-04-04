import random
import time

from curl_cffi import CurlHttpVersion, requests
from curl_cffi.requests import AsyncSession


async def create_shared_async_session():
    browsers = ["chrome120", "chrome99_android"]
    selected_browsers = random.choice(browsers)
    async with AsyncSession(
            impersonate=selected_browsers,
            http_version=CurlHttpVersion.V2TLS,
    ) as session:
        yield session


def create_shared_session():
    random.seed(int(time.time()))
    browsers = ["chrome120", "chrome99_android"]
    selected_browsers = random.choice(browsers)
    session = requests.Session(impersonate=selected_browsers,
                               http_version=CurlHttpVersion.V2TLS, timeout=15)
    return session
