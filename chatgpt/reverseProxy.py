import random

from fastapi import Request, HTTPException
from fastapi.responses import StreamingResponse, Response

from utils.Client import Client
from utils.config import chatgpt_base_url_list, proxy_url_list


async def chatgpt_reverse_proxy(request: Request, path: str):
    base_url = random.choice(chatgpt_base_url_list)
    if ":" in request.url.netloc:
        origin_url = "http://" + request.url.netloc
    else:
        origin_url = "https://" + request.url.netloc
    if "v1" in path:
        base_url = "https://ab.chatgpt.com"
    params = dict(request.query_params)
    headers = {key: value for key, value in request.headers.items() if
               key.lower() not in ["host", "origin", "referer", "user-agent", "authorization"]}
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

    try:
        r = await client.request(request.method, f"{base_url}/{path}", params=params, headers=headers, cookies=cookies,
                                 data=data, stream=True)
        if 'stream' in r.headers.get("content-type", ""):
            return StreamingResponse(r.aiter_content(), media_type=r.headers.get("content-type", ""))
        else:
            content = (await r.atext()).replace("https://chat.openai.com", origin_url).replace("https://ab.chatgpt.com",
                                                                                               origin_url).replace(
                "https://cdn.oaistatic.com", origin_url)
            return Response(content=content, media_type=r.headers.get("content-type"), status_code=r.status_code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
