"""chat2api 管理后台 API 客户端。

鉴权：直接带 Cookie `admin_auth=<ADMIN_PASSWORD>`（chat2api 的 cookie 值就是密码本身，
见 gateway/admin.py::routing_admin_login_submit）。省去登录表单提交一步。
"""

import logging
from typing import Dict, List, Optional

import httpx


logger = logging.getLogger("harvester")


class Chat2ApiClient:
    def __init__(self, base_url: str, api_prefix: str, admin_password: str):
        self.base = base_url.rstrip("/")
        self.prefix = f"/{api_prefix}" if api_prefix else ""
        self._cookie_header = f"admin_auth={admin_password}"

    def _url(self, path: str) -> str:
        return f"{self.base}{self.prefix}{path}"

    async def healthcheck(self) -> bool:
        """调 /admin/routing/data 探测：鉴权 + 可达双重验证。"""
        url = self._url("/admin/routing/data")
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(url, headers={"Cookie": self._cookie_header})
            if r.status_code == 401:
                logger.error("chat2api 鉴权失败：请检查 CHAT2API_ADMIN_PASSWORD")
                return False
            if r.status_code == 503:
                logger.error(
                    "chat2api 后台已禁用：请在 docker-compose 里配置 ADMIN_PASSWORD"
                )
                return False
            r.raise_for_status()
            return True
        except httpx.RequestError as e:
            logger.error(f"chat2api 不可达: {e}")
            return False

    async def list_proxies(self) -> List[Dict]:
        """返回 [{'name': 'HK-Resi-01', 'proxy_url': '...'}]。"""
        url = self._url("/admin/routing/data")
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(url, headers={"Cookie": self._cookie_header})
            r.raise_for_status()
            return r.json().get("proxy_options", [])

    async def resolve_proxy(self, proxy_name: str) -> Optional[str]:
        """根据 name 反查 proxy_url；找不到返回 None。"""
        if not proxy_name:
            return None
        for item in await self.list_proxies():
            if item.get("name") == proxy_name:
                return item.get("proxy_url")
        return None

    async def import_token(
        self,
        refresh_token: str,
        note: str = "",
        proxy_name: str = "",
        proxy_url: str = "",
        group_name: str = "",
    ) -> Dict:
        """把单个 rt 写入 chat2api 账号池。

        注意：这里默认 overwrite_existing=False，重复 rt 会被 chat2api 静默跳过。
        """
        url = self._url("/admin/routing/accounts/import")
        payload = {
            "text": refresh_token,
            "note": note,
            "group_name": group_name,
            "proxy_name": proxy_name,
            "proxy_url": proxy_url,
            "overwrite_existing": False,
        }
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                url,
                json=payload,
                headers={
                    "Cookie": self._cookie_header,
                    "Content-Type": "application/json",
                },
            )
        if r.status_code == 401:
            raise RuntimeError("chat2api 鉴权失败（ADMIN_PASSWORD 不对）")
        if r.status_code == 503:
            raise RuntimeError("chat2api 后台未开启（未配置 ADMIN_PASSWORD）")
        r.raise_for_status()
        return r.json()

    async def report_harvest(
        self,
        email: str,
        rt_prefix: str = "",
        success: bool = True,
        error: str = "",
        imported_token: str = "",
    ) -> None:
        """把采集结果上报给 chat2api，更新 Harvester 看板的 last_rt_prefix / 状态。

        失败不抛异常，避免因元数据回传问题污染主流程。
        """
        url = self._url("/admin/harvester/report")
        payload = {
            "email": email,
            "success": success,
            "rt_prefix": rt_prefix,
            "error": error,
            "imported_token": imported_token,
        }
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(
                    url,
                    json=payload,
                    headers={
                        "Cookie": self._cookie_header,
                        "Content-Type": "application/json",
                    },
                )
            if r.status_code != 200:
                logger.warning(
                    f"report_harvest 返回 {r.status_code}: {r.text[:200]}"
                )
        except Exception as e:
            logger.warning(f"report_harvest 失败（忽略）: {e}")
