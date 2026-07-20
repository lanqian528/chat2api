"""ChatService 子职责 Mixin 包。

各 Mixin 通过 self.* 共享 ChatService 实例状态：
- AuthMixin：rese_auth_context（req_token -> access_token + account_id）
- ModelMixin：模型解析、上游模型列表缓存、可用性校验
- FileMixin：文件上传/下载相关的 8 个上游端点封装
"""

from chatgpt.services.auth_mixin import AuthMixin
from chatgpt.services.file_mixin import FileMixin
from chatgpt.services.model_mixin import ModelMixin

__all__ = ["AuthMixin", "FileMixin", "ModelMixin"]
