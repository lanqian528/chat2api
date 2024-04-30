import random

from fastapi import Request, HTTPException
from fastapi.responses import StreamingResponse, Response
from starlette.background import BackgroundTask

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
        origin_host = request.url.netloc
        if ":" in origin_host:
            petrol = "http"
        else:
            petrol = "https"
        if path.startswith("v1/"):
            base_url = "https://ab.chatgpt.com"
        else:
            base_url = random.choice(chatgpt_base_url_list)
        params = dict(request.query_params)
        headers = {
            key: value for key, value in request.headers.items()
            if (key.lower() not in ["host", "origin", "referer", "user-agent",
                                    "authorization"] and key.lower() not in headers_reject_list)
        }
        cookies = dict(request.cookies)

        headers.update({
            "accept-Language": "en-US,en;q=0.9",
            "host": base_url.replace("https://", "").replace("http://", ""),
            "origin": base_url,
            "referer": f"{base_url}/",
            "sec-ch-ua": '"Chromium";v="124", "Microsoft Edge";v="124", "Not-A.Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "\"Windows\"",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
        })

        if request.headers.get('Authorization'):
            headers['Authorization'] = request.headers['Authorization']

        if headers.get("Content-Type") == "application/json":
            data = await request.json()
        else:
            data = await request.body()

        client = Client(proxy=random.choice(proxy_url_list) if proxy_url_list else None)
        r = None
        try:
            r = await client.request(request.method, f"{base_url}/{path}", params=params, headers=headers, cookies=cookies, data=data, stream=True)
            if r.status_code == 302:
                return Response(status_code=302, headers={"Location": r.headers.get("Location")})
            elif 'stream' in r.headers.get("content-type", ""):
                background = BackgroundTask(client.close)
                return StreamingResponse(r.aiter_content(), media_type=r.headers.get("content-type", ""), background=background)
            else:
                content = ((await r.atext()).replace("chat.openai.com", origin_host)
                           .replace("ab.chatgpt.com", origin_host)
                           .replace("cdn.oaistatic.com", origin_host)
                           .replace("https", petrol))
                response = Response(content=content, media_type=r.headers.get("content-type"), status_code=r.status_code)
                for key, value in r.cookies.items():
                    if key in cookies.keys():
                        continue
                    response.set_cookie(key=key, value=value)
                return response
        finally:
            if r and 'stream' not in r.headers.get("content-type", ""):
                await client.close()

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
