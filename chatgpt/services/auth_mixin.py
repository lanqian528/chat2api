"""认证上下文解析 Mixin。

封装从 req_token 解析 access_token 与 account_id 的逻辑。
原始位置：chatgpt/ChatService.py:146-158
"""

from chatgpt.authorization import verify_token
from utils.Logger import logger


class AuthMixin:
    async def resolve_auth_context(self):
        if self.req_token:
            req_len = len(self.req_token.split(","))
            if req_len == 1:
                self.access_token = await verify_token(self.req_token)
                self.account_id = None
            else:
                self.access_token = await verify_token(self.req_token.split(",")[0])
                self.account_id = self.req_token.split(",")[1]
        else:
            logger.info("Request token is empty, use no-auth 3.5")
            self.access_token = None
            self.account_id = None
