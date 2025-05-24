import random

from curl_cffi import CurlOpt
from curl_cffi.requests import AsyncSession


class Client:
    def __init__(self, proxy=None, timeout=30, verify=True, impersonate='safari17_2_ios'):
        self.proxies = {"http": proxy, "https": proxy}
        self.timeout = timeout
        self.verify = verify

        self.impersonate = impersonate
        # impersonate=self.impersonate

        # self.ja3 = ""
        # self.akamai = ""
        # ja3=self.ja3, akamai=self.akamai
        curl_options = {
            CurlOpt.LOW_SPEED_LIMIT: 1,
            CurlOpt.LOW_SPEED_TIME: 30
        }
        self.session = AsyncSession(proxies=self.proxies, timeout=self.timeout, impersonate=self.impersonate, verify=self.verify, curl_options=curl_options)

    async def post(self, *args, **kwargs):
        r = await self.session.post(*args, **kwargs)
        return r

    async def post_stream(self, *args, **kwargs):
        r = await self.session.post(*args, **kwargs)
        return r

    async def get(self, *args, **kwargs):
        r = await self.session.get(*args, **kwargs)
        return r

    async def request(self, *args, **kwargs):
        r = await self.session.request(*args, **kwargs)
        return r

    async def put(self, *args, **kwargs):
        r = await self.session.put(*args, **kwargs)
        return r

    async def close(self):
        if hasattr(self, 'session'):
            try:
                await self.session.close()
                del self.session
            except Exception:
                pass
