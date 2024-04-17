from curl_cffi.requests import AsyncSession


class Client:
    def __init__(self, proxy=None, timeout=30, verify=True):
        self.proxy = proxy
        self.timeout = timeout
        self.verify = verify
        self.headers = None
        self.cookies = None

    async def post(self, *args, headers=None, cookies=None, **kwargs):
        if not headers:
            headers = self.headers
        if not cookies:
            cookies = self.cookies
        s = AsyncSession(proxies=self.proxy, timeout=self.timeout, verify=self.verify)
        r = await s.post(*args, headers=headers, cookies=cookies, **kwargs)
        self.cookies = r.cookies
        return r

    async def get(self, *args, headers=None, cookies=None, **kwargs):
        s = AsyncSession(proxies=self.proxy, timeout=self.timeout, verify=self.verify)
        if not headers:
            headers = self.headers
        if not cookies:
            cookies = self.cookies
        r = await s.get(*args, headers=headers, cookies=cookies, **kwargs)
        self.cookies = r.cookies
        return r
