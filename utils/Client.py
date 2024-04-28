import random

from curl_cffi.requests import AsyncSession


class Client:
    def __init__(self, proxy=None, timeout=30, verify=True):
        self.proxies = {
            "http": proxy,
            "https": proxy,
        }
        self.timeout = timeout
        self.verify = verify
        self.headers = None
        self.cookies = None
        self.impersonate = random.choice(["chrome", "safari", "safari_ios"])

    async def post(self, *args, headers=None, cookies=None, **kwargs):
        if not headers:
            headers = self.headers
        if not cookies:
            cookies = self.cookies
        s = AsyncSession(proxies=self.proxies, timeout=self.timeout, verify=self.verify)
        r = await s.post(*args, headers=headers, cookies=cookies, impersonate=self.impersonate, **kwargs)
        self.cookies = r.cookies
        return r

    async def get(self, *args, headers=None, cookies=None, **kwargs):
        if not headers:
            headers = self.headers
        if not cookies:
            cookies = self.cookies
        async with AsyncSession(proxies=self.proxies, timeout=self.timeout, verify=self.verify) as s:
            r = await s.get(*args, headers=headers, cookies=cookies, impersonate=self.impersonate, **kwargs)
            self.cookies = r.cookies
            return r

    async def request(self, *args, headers=None, cookies=None, **kwargs):
        if not headers:
            headers = self.headers
        if not cookies:
            cookies = self.cookies
        async with AsyncSession(proxies=self.proxies, timeout=self.timeout, verify=self.verify) as s:
            r = await s.request(*args, headers=headers, cookies=cookies, impersonate=self.impersonate, **kwargs)
            self.cookies = r.cookies
            return r

    async def put(self, *args, headers=None, cookies=None, **kwargs):
        if not headers:
            headers = self.headers
        if not cookies:
            cookies = self.cookies
        async with AsyncSession(proxies=self.proxies, timeout=self.timeout, verify=self.verify) as s:
            r = await s.put(*args, headers=headers, cookies=cookies, impersonate=self.impersonate, **kwargs)
            self.cookies = r.cookies
            return r

