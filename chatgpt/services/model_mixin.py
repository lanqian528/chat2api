"""模型解析与上游模型校验 Mixin。

负责：
- 上游可用模型列表的拉取与缓存（host + account + token 维度，TTL 300s）
- 请求模型解析（origin -> req/resp/gizmo/dynamic）
- 模型可用性校验，统一 404 model_not_found 语义

原始位置：chatgpt/ChatService.py:87-144 / 293-303
"""

import hashlib
import time

from fastapi import HTTPException

from api.models import augment_model_slugs, extract_model_slugs, get_response_model, resolve_request_model
from utils.configs import check_model
from utils.Logger import logger


class ModelMixin:
    available_model_cache = {}
    available_model_cache_ttl = 300

    def model_not_found(self):
        return HTTPException(
            status_code=404,
            detail={
                "message": f"The model `{self.origin_model}` does not exist or you do not have access to it.",
                "type": "invalid_request_error",
                "param": None,
                "code": "model_not_found",
            },
        )

    def get_model_cache_key(self):
        token = self.req_token.split(",")[0] if self.req_token else "anon"
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        account_id = self.account_id or "default"
        return f"{self.host_url}:{account_id}:{token_hash}"

    async def fetch_available_models(self):
        cache_key = self.get_model_cache_key()
        now = time.time()
        cached = self.available_model_cache.get(cache_key)
        if cached and now - cached["time"] < self.available_model_cache_ttl:
            return cached["slugs"]

        url = f"{self.host_url}/backend-api/models?history_and_training_disabled={str(self.history_disabled).lower()}"
        headers = self.base_headers.copy()
        r = await self.s.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            detail = r.text
            if "application/json" in r.headers.get("Content-Type", ""):
                detail = r.json().get("detail", r.json())
            raise HTTPException(status_code=r.status_code, detail=detail)

        models_payload = r.json()
        model_slugs = augment_model_slugs(extract_model_slugs(models_payload))
        self.available_model_cache[cache_key] = {
            "time": now,
            "slugs": model_slugs,
        }
        logger.info(f"Available models exposed: {len(model_slugs)}")
        return model_slugs

    async def validate_model_access(self):
        if self.gizmo_id:
            return

        if not self.access_token:
            if self.req_model != "text-davinci-002-render-sha":
                raise self.model_not_found()
            return

        if not (self.dynamic_model or check_model):
            return

        available_models = await self.fetch_available_models()
        if self.req_model not in available_models:
            logger.error(f"Model {self.req_model} not found in upstream models")
            raise self.model_not_found()

    async def set_model(self):
        self.origin_model = self.data.get("model", "gpt-5-5")
        self.resp_model = get_response_model(self.origin_model)
        self.req_model, self.gizmo_id, self.dynamic_model = resolve_request_model(self.origin_model)

        # 深度研究：模型名后缀识别（双模式触发之二）
        # 当模型名包含 deep-research / deepresearch 时，自动注入 system_hints=["research"]
        lower_origin = (self.origin_model or "").lower()
        if "deep-research" in lower_origin or "deepresearch" in lower_origin:
            if "research" not in self.system_hints:
                self.system_hints = list(self.system_hints) + ["research"]
