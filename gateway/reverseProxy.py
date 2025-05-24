import hashlib
import json
import random
import time
from datetime import datetime, timezone

from fastapi import Request, HTTPException
from fastapi.responses import StreamingResponse, Response
from starlette.background import BackgroundTask

import utils.globals as globals
from chatgpt.authorization import verify_token, get_req_token
from chatgpt.fp import get_fp
from utils.Client import Client
from utils.Logger import logger
from utils.configs import chatgpt_base_url_list, sentinel_proxy_url_list, force_no_history, file_host, voice_host


def generate_current_time():
    current_time = datetime.now(timezone.utc)
    formatted_time = current_time.isoformat(timespec='microseconds').replace('+00:00', 'Z')
    return formatted_time


headers_reject_list = [
    "x-real-ip",
    "x-forwarded-for",
    "x-forwarded-proto",
    "x-forwarded-port",
    "x-forwarded-host",
    "x-forwarded-server",
    "cf-warp-tag-id",
    "cf-visitor",
    "cf-ray",
    "cf-connecting-ip",
    "cf-ipcountry",
    "cdn-loop",
    "remote-host",
    "x-frame-options",
    "x-xss-protection",
    "x-content-type-options",
    "content-security-policy",
    "host",
    "cookie",
    "connection",
    "content-length",
    "content-encoding",
    "x-middleware-prefetch",
    "x-nextjs-data",
    "purpose",
    "x-forwarded-uri",
    "x-forwarded-path",
    "x-forwarded-method",
    "x-forwarded-protocol",
    "x-forwarded-scheme",
    "cf-request-id",
    "cf-worker",
    "cf-access-client-id",
    "cf-access-client-device-type",
    "cf-access-client-device-model",
    "cf-access-client-device-name",
    "cf-access-client-device-brand",
    "x-middleware-prefetch",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-forwarded-server",
    "x-real-ip",
    "x-forwarded-port",
    "cf-connecting-ip",
    "cf-ipcountry",
    "cf-ray",
    "cf-visitor",
]

headers_accept_list = [
    "openai-sentinel-chat-requirements-token",
    "openai-sentinel-proof-token",
    "openai-sentinel-turnstile-token",
    "accept",
    "authorization",
    "accept-encoding",
    "accept-language",
    "content-type",
    "oai-device-id",
    "oai-echo-logs",
    "oai-language",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
]


async def get_real_req_token(token):
    req_token = get_req_token(token)
    if len(req_token) == 45 or req_token.startswith("eyJhbGciOi"):
        return req_token
    else:
        req_token = get_req_token("", token)
        return req_token


def save_conversation(token, conversation_id, title=None):
    if conversation_id not in globals.conversation_map:
        conversation_detail = {
            "id": conversation_id,
            "title": title,
            "create_time": generate_current_time(),
            "update_time": generate_current_time()
        }
        globals.conversation_map[conversation_id] = conversation_detail
    else:
        globals.conversation_map[conversation_id]["update_time"] = generate_current_time()
        if title:
            globals.conversation_map[conversation_id]["title"] = title
    if conversation_id not in globals.seed_map[token]["conversations"]:
        globals.seed_map[token]["conversations"].insert(0, conversation_id)
    else:
        globals.seed_map[token]["conversations"].remove(conversation_id)
        globals.seed_map[token]["conversations"].insert(0, conversation_id)
    with open(globals.CONVERSATION_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(globals.conversation_map, f, indent=4)
    with open(globals.SEED_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(globals.seed_map, f, indent=4)
    if title:
        logger.info(f"Conversation ID: {conversation_id}, Title: {title}")


async def content_generator(r, token, history=True):
    conversation_id = None
    title = None
    async for chunk in r.aiter_content():
        try:
            if history and (len(token) != 45 and not token.startswith("eyJhbGciOi")) and (not conversation_id or not title):
                chat_chunk = chunk.decode('utf-8')
                if not conversation_id or not title and chat_chunk.startswith("event: delta\n\ndata: {"):
                    chunk_data = chat_chunk[19:]
                    conversation_id = json.loads(chunk_data).get("v").get("conversation_id")
                    if conversation_id:
                        save_conversation(token, conversation_id)
                        title = globals.conversation_map[conversation_id].get("title")
                if chat_chunk.startswith("data: {"):
                    if "\n\nevent: delta" in chat_chunk:
                        index = chat_chunk.find("\n\nevent: delta")
                        chunk_data = chat_chunk[6:index]
                    elif "\n\ndata: {" in chat_chunk:
                        index = chat_chunk.find("\n\ndata: {")
                        chunk_data = chat_chunk[6:index]
                    else:
                        chunk_data = chat_chunk[6:]
                    chunk_data = chunk_data.strip()
                    if conversation_id is None:
                        conversation_id = json.loads(chunk_data).get("conversation_id")
                        if conversation_id:
                            save_conversation(token, conversation_id)
                            title = globals.conversation_map[conversation_id].get("title")
                    if title is None:
                        title = json.loads(chunk_data).get("title")
                        if title:
                            save_conversation(token, conversation_id, title)
        except Exception as e:
            # logger.error(e)
            # logger.error(chunk.decode('utf-8'))
            pass
        yield chunk


async def chatgpt_reverse_proxy(request: Request, path: str):
    try:
        origin_host = request.url.netloc
        if request.url.is_secure:
            petrol = "https"
        else:
            petrol = "http"
        if "x-forwarded-proto" in request.headers:
            petrol = request.headers["x-forwarded-proto"]
        if "cf-visitor" in request.headers:
            cf_visitor = json.loads(request.headers["cf-visitor"])
            petrol = cf_visitor.get("scheme", petrol)

        params = dict(request.query_params)
        request_cookies = dict(request.cookies)

        # headers = {
        #     key: value for key, value in request.headers.items()
        #     if (key.lower() not in ["host", "origin", "referer", "priority",
        #                             "oai-device-id"] and key.lower() not in headers_reject_list)
        # }
        headers = {
            key: value for key, value in request.headers.items()
            if (key.lower() in headers_accept_list)
        }

        base_url = random.choice(chatgpt_base_url_list) if chatgpt_base_url_list else "https://chatgpt.com"
        if "assets/" in path:
            base_url = "https://cdn.oaistatic.com"
        if "file-" in path and "backend-api" not in path:
            base_url = "https://files.oaiusercontent.com"
        if "v1/" in path:
            base_url = "https://ab.chatgpt.com"
        if "sandbox" in path:
            base_url = "https://web-sandbox.oaiusercontent.com"
            path = path.replace("sandbox/", "")

        token = headers.get("authorization", "").replace("Bearer ", "").strip()
        if token:
            req_token = await get_real_req_token(token)
            access_token = await verify_token(req_token)
            headers.update({"authorization": f"Bearer {access_token}"})

        cookie_token = request.cookies.get("token", "")
        req_token = await get_real_req_token(cookie_token)
        fp = get_fp(req_token).copy()

        session_id = hashlib.md5(req_token.encode()).hexdigest()

        proxy_url = fp.pop("proxy_url", None)
        impersonate = fp.pop("impersonate", "safari15_3")
        user_agent = fp.get("user-agent")
        headers.update(fp)

        headers.update({
            "accept-language": "en-US,en;q=0.9",
            "host": base_url.replace("https://", "").replace("http://", ""),
            "origin": base_url,
            "referer": f"{base_url}/"
        })
        if "v1/initialize" in path:
            headers.update({"user-agent": request.headers.get("user-agent")})
            if "statsig-api-key" not in headers:
                headers.update({
                    "statsig-sdk-type": "js-client",
                    "statsig-api-key": "client-tnE5GCU2F2cTxRiMbvTczMDT1jpwIigZHsZSdqiy4u",
                    "statsig-sdk-version": "5.1.0",
                    "statsig-client-time": int(time.time() * 1000),
                })

        data = await request.body()

        history = True
        if path.endswith("backend-api/conversation") or path.endswith("backend-alt/conversation"):
            try:
                req_json = json.loads(data)
                history = not req_json.get("history_and_training_disabled", False)
            except Exception:
                pass
            if force_no_history:
                history = False
                req_json = json.loads(data)
                req_json["history_and_training_disabled"] = True
                data = json.dumps(req_json).encode("utf-8")


        if "backend-api/sentinel/chat-requirements" in path and sentinel_proxy_url_list:
            sentinel_proxy_url = random.choice(sentinel_proxy_url_list).replace("{}", session_id) if sentinel_proxy_url_list else None
            client = Client(proxy=sentinel_proxy_url)
        else:
            proxy_url = proxy_url.replace("{}", session_id) if proxy_url else None
            client = Client(proxy=proxy_url, impersonate=impersonate)
        try:
            background = BackgroundTask(client.close)
            r = await client.request(request.method, f"{base_url}/{path}", params=params, headers=headers,
                                     cookies=request_cookies, data=data, stream=True, allow_redirects=False)
            if r.status_code == 307 or r.status_code == 302 or r.status_code == 301:
                return Response(status_code=307,
                                headers={"Location": r.headers.get("Location")
                                .replace("ab.chatgpt.com", origin_host)
                                .replace("chatgpt.com", origin_host)
                                .replace("cdn.oaistatic.com", origin_host)
                                .replace("https", petrol)}, background=background)
            elif 'stream' in r.headers.get("content-type", ""):
                if path.endswith("backend-api/conversation") or path.endswith("backend-alt/conversation"):
                    logger.info(f"Request token: {req_token}")
                    logger.info(f"Request proxy: {proxy_url}")
                    logger.info(f"Request UA: {user_agent}")
                    logger.info(f"Request impersonate: {impersonate}")

                response = StreamingResponse(content_generator(r, token, history), media_type=r.headers.get("content-type", ""),
                                  background=background)
                conv_key = r.cookies.get("conv_key", "")
                if conv_key:
                    response.set_cookie("conv_key", value=conv_key)
                return response
            elif 'image' in r.headers.get("content-type", "") or "audio" in r.headers.get("content-type", "") or "video" in r.headers.get("content-type", ""):
                rheaders = dict(r.headers)
                response = Response(content=await r.acontent(), headers=rheaders,
                                        status_code=r.status_code, background=background)
                return response
            else:
                if path.endswith("backend-api/conversation") or path.endswith("backend-alt/conversation") or "/register-websocket" in path:
                    response = Response(content=(await r.acontent()), media_type=r.headers.get("content-type"),
                                        status_code=r.status_code, background=background)
                else:
                    content = await r.atext()
                    if "public-api/" in path:
                        content = (content
                                   .replace("https://ab.chatgpt.com", f"{petrol}://{origin_host}")
                                   .replace("https://cdn.oaistatic.com", f"{petrol}://{origin_host}")
                                   .replace("webrtc.chatgpt.com", voice_host if voice_host else "webrtc.chatgpt.com")
                                   .replace("files.oaiusercontent.com", file_host if file_host else "files.oaiusercontent.com")
                                   .replace("chatgpt.com/ces", f"{origin_host}/ces")
                                   )
                    else:
                        content = (content
                                   .replace("https://ab.chatgpt.com", f"{petrol}://{origin_host}")
                                   .replace("https://cdn.oaistatic.com", f"{petrol}://{origin_host}")
                                   .replace("webrtc.chatgpt.com", voice_host if voice_host else "webrtc.chatgpt.com")
                                   .replace("files.oaiusercontent.com", file_host if file_host else "files.oaiusercontent.com")
                                   .replace("web-sandbox.oaiusercontent.com", f"{origin_host}/sandbox")
                                   .replace("https://chatgpt.com", f"{petrol}://{origin_host}")
                                   .replace("chatgpt.com/ces", f"{origin_host}/ces")
                                   )
                    if base_url == "https://web-sandbox.oaiusercontent.com":
                        content = content.replace("/assets", "/sandbox/assets")
                    rheaders = dict(r.headers)
                    content_type = rheaders.get("content-type", "")
                    cache_control = rheaders.get("cache-control", "")
                    expires = rheaders.get("expires", "")
                    content_disposition = rheaders.get("content-disposition", "")
                    rheaders = {
                        "cache-control": cache_control,
                        "content-type": content_type,
                        "expires": expires,
                        "content-disposition": content_disposition
                    }
                    response = Response(content=content, headers=rheaders,
                                        status_code=r.status_code, background=background)
                return response
        except Exception as e:
            await client.close()
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
