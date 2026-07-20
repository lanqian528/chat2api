"""OpenAI 兼容的图片生成端点。

POST /v1/images/generations

内部实现：把图片生成请求转换为强制触发 ChatGPT 网页 dalle.text2im 工具
的 chat 对话，解析响应里的 markdown 图片 URL，包装为 OpenAI 格式返回。

支持 OpenAI 标准参数：prompt / model / n / size / quality / style /
response_format（url | b64_json）。
"""

import asyncio
import base64
import re
import time

from fastapi import HTTPException, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials

from app import app, security_scheme
from api.chat2api import process
from chatgpt.ChatService import ChatService
from utils.configs import api_prefix
from utils.Logger import logger
from utils.retry import async_retry


IMAGE_MARKDOWN_RE = re.compile(r"!\[(?:image|File\s*\d+)\]\(([^)]+)\)", re.IGNORECASE)
DEFAULT_CHAT_MODEL = "gpt-5-5"
MAX_CONCURRENT_IMAGES = 4
MAX_IMAGES_PER_REQUEST = 10
IMAGE_DOWNLOAD_TIMEOUT = 30
ALLOWED_RESPONSE_FORMATS = ("url", "b64_json")


def _build_image_generation_prompt(prompt, size, quality, style):
    """构造强制触发 dalle.text2im 的 prompt 文本。"""
    lines = [
        "Use the image generation tool dalle.text2im to create an image for the following description:",
        f'"{prompt}"',
    ]
    if size:
        lines.append(f"Size: {size}")
    if quality:
        lines.append(f"Quality: {quality}")
    if style:
        lines.append(f"Style: {style}")
    lines.append("Generate the image directly. Do not ask for clarification.")
    return "\n".join(lines)


def _extract_image_urls(content):
    """从 chat 响应内容里提取所有图片 URL。"""
    if not content:
        return []
    return [m.group(1).strip() for m in IMAGE_MARKDOWN_RE.finditer(content)]


async def _resolve_target_model(req_token, requested_model):
    """动态选 model：探测上游可用列表，命中即用，否则 fallback gpt-5-5。

    使用临时 ChatService 实例只做模型探测，用完即关闭，与后续图片生成调用不共享。
    """
    probe = ChatService(req_token)
    try:
        await probe.resolve_auth_context()
        await probe.initialize_request_context()
        slugs = await probe.fetch_available_models()
        if requested_model and requested_model in slugs:
            return requested_model
    except Exception as e:
        logger.warning(f"[image_gen] resolve_target_model failed, fallback gpt-5-5: {e}")
    finally:
        try:
            await probe.close_client()
        except Exception:
            pass
    return DEFAULT_CHAT_MODEL


async def _download_image_to_b64(chat_service, url):
    """复用 chat_service 的 curl_cffi 客户端下载图片并 base64 编码。"""
    headers = (getattr(chat_service, "base_headers", None) or {}).copy()
    headers.pop("content-type", None)
    try:
        r = await chat_service.s.get(url, headers=headers, timeout=IMAGE_DOWNLOAD_TIMEOUT)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to download image: {str(e)}")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Failed to download image: status {r.status_code}")
    return base64.b64encode(r.content).decode("ascii")


async def _generate_single_image(req_token, target_model, prompt, size, quality, style):
    """执行一次图片生成 chat 流程，返回 (chat_service, content, urls)。

    成功时 chat_service 不在此处关闭，由上层 finally 统一释放（便于复用其客户端下载图片）。
    """
    chat_request = {
        "model": target_model,
        "messages": [
            {
                "role": "user",
                "content": _build_image_generation_prompt(prompt, size, quality, style),
            }
        ],
        "stream": False,
    }
    chat_service, res = await async_retry(process, chat_request, req_token)
    try:
        content = ((res or {}).get("choices") or [{}])[0].get("message", {}).get("content", "")
        urls = _extract_image_urls(content)
        return chat_service, content, urls
    except Exception:
        await chat_service.close_client()
        raise


def _validate_payload(payload):
    """校验请求参数，返回标准化的字段元组。"""
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": "prompt is required",
                    "type": "invalid_request_error",
                    "param": "prompt",
                }
            },
        )

    n = payload.get("n", 1)
    if not isinstance(n, int) or n < 1 or n > MAX_IMAGES_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": f"n must be int in [1, {MAX_IMAGES_PER_REQUEST}]",
                    "type": "invalid_request_error",
                    "param": "n",
                }
            },
        )

    response_format = (payload.get("response_format") or "url").lower()
    if response_format not in ALLOWED_RESPONSE_FORMATS:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": f"response_format must be one of {ALLOWED_RESPONSE_FORMATS}",
                    "type": "invalid_request_error",
                    "param": "response_format",
                }
            },
        )

    return {
        "prompt": prompt,
        "n": n,
        "size": payload.get("size") or "1024x1024",
        "quality": payload.get("quality"),
        "style": payload.get("style"),
        "requested_model": payload.get("model"),
        "response_format": response_format,
    }


@app.post(f"/{api_prefix}/v1/images/generations" if api_prefix else "/v1/images/generations")
async def generate_images(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(security_scheme),
):
    req_token = credentials.credentials
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail={"error": "Invalid JSON body"})

    params = _validate_payload(payload)
    target_model = await _resolve_target_model(req_token, params["requested_model"])
    logger.info(f"[image_gen] target_model={target_model} n={params['n']} format={params['response_format']}")

    # 并发 n 次生成，并发上限 MAX_CONCURRENT_IMAGES
    semaphore = asyncio.Semaphore(min(params["n"], MAX_CONCURRENT_IMAGES))

    async def _one():
        async with semaphore:
            return await _generate_single_image(
                req_token,
                target_model,
                params["prompt"],
                params["size"],
                params["quality"],
                params["style"],
            )

    results = await asyncio.gather(*[_one() for _ in range(params["n"])], return_exceptions=True)

    services_to_close = []
    image_items = []
    failure_excerpts = []
    try:
        for r in results:
            if isinstance(r, Exception):
                failure_excerpts.append(str(r)[:200])
                continue
            svc, content, urls = r
            services_to_close.append(svc)
            if not urls:
                failure_excerpts.append((content or "")[:200])
                continue
            url = urls[0]
            if params["response_format"] == "url":
                image_items.append({"url": url})
            else:
                try:
                    b64 = await _download_image_to_b64(svc, url)
                    image_items.append({"b64_json": b64})
                except HTTPException as e:
                    failure_excerpts.append(f"download failed: {e.detail}")

        if not image_items:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "message": "Failed to generate image",
                        "type": "image_generation_failed",
                        "code": "no_image_generated",
                        "upstream_excerpt": failure_excerpts[0] if failure_excerpts else "",
                    }
                },
            )

        return JSONResponse(
            {"created": int(time.time()), "data": image_items},
            media_type="application/json",
        )
    finally:
        for svc in services_to_close:
            try:
                await svc.close_client()
            except Exception:
                pass
