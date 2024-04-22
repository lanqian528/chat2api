import random
from fastapi import Request, HTTPException
from fastapi.responses import StreamingResponse, Response

from utils.Client import Client
from utils.config import chatgpt_base_url_list, proxy_url_list


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

async def chatgpt_reverse_proxy(request: Request, path: str):
    try:
        base_url = random.choice(chatgpt_base_url_list)
        origin_host = request.url.netloc
        if ":" in origin_host:
            petrol = "http"
        else:
            petrol = "https"
        if path.startswith("v1/"):
            base_url = "https://ab.chatgpt.com"
        if path.startswith("authorize") and "max_age" not in dict(request.query_params).keys():
            base_url = "https://auth.openai.com"
        if path.startswith("authorize") or path.startswith("u/") or path.startswith("oauth/") or path.startswith("assets/"):
            base_url = "https://auth0.openai.com"
        params = dict(request.query_params)
        headers = {
            key: value for key, value in request.headers.items()
            if (key.lower() not in ["host", "origin", "referer", "user-agent", "authorization"] and key.lower() not in headers_reject_list)
        }
        cookies = dict(request.cookies)

        headers.update({
            "Accept-Language": "en-US,en;q=0.9",
            "Host": f"{base_url.split('//')[1]}",
            "Origin": f"{base_url}",
            "Referer": f"{base_url}/{path}",
            "Sec-Ch-Ua": '"Chromium";v="123", "Not(A:Brand";v="24", "Microsoft Edge";v="123"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": "\"Windows\"",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0"
        })
        if request.headers.get('Authorization'):
            headers['Authorization'] = request.headers['Authorization']

        if headers.get("Content-Type") == "application/json":
            data = await request.json()
        else:
            data = await request.body()

        client = Client(proxy=random.choice(proxy_url_list) if proxy_url_list else None)

        r = await client.request(request.method, f"{base_url}/{path}", params=params, headers=headers, cookies=cookies,
                                 data=data, stream=True)
        if 'stream' in r.headers.get("content-type", ""):
            return StreamingResponse(r.aiter_content(), media_type=r.headers.get("content-type", ""))
        else:
            content = ((await r.atext()).replace("chat.openai.com", origin_host)
                       .replace("ab.chatgpt.com", origin_host)
                       .replace("cdn.oaistatic.com", origin_host)
                       .replace("auth.openai.com", origin_host)
                       .replace("auth0.openai.com", origin_host)
                       .replace("https", petrol))
            response = Response(content=content, media_type=r.headers.get("content-type"), status_code=r.status_code)
            for key, value in r.cookies.items():
                if key in cookies.keys():
                    continue
                if key.startswith("__"):
                    response.set_cookie(key=key, value=value, secure=True, httponly=True, path='/')
                else:
                    response.set_cookie(key=key, value=value, secure=True, httponly=True)
            return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
