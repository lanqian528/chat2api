import random

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, Response

from chatgpt.ChatService import ChatService
from utils.Client import Client
from utils.authorization import verify_token
from utils.config import chatgpt_base_url_list, proxy_url_list
from utils.retry import async_retry

app = FastAPI()


async def to_send_conversation(request_data, access_token):
    chat_service = ChatService(request_data, access_token)
    await chat_service.get_chat_requirements()
    return chat_service


@app.post("/v1/chat/completions")
async def send_conversation(request: Request, token=Depends(verify_token)):
    access_token = None
    if token and token.startswith("eyJhbGciOi"):
        access_token = token
    try:
        request_data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail={"error": "Invalid JSON body"})

    chat_service = await async_retry(to_send_conversation, request_data, access_token)
    chat_service.prepare_send_conversation()

    stream = request_data.get("stream", False)
    if stream is True:
        return StreamingResponse(await chat_service.send_conversation_for_stream(), media_type="text/event-stream")
    else:
        return JSONResponse(await chat_service.send_conversation(), media_type="application/json")


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH", "TRACE"])
async def proxy(request: Request, path: str):
    base_url = random.choice(chatgpt_base_url_list)
    params = dict(request.query_params)
    headers = {key: value for key, value in request.headers.items() if key.lower() not in ["host", "origin", "referer", "user-agent", "authorization"]}
    cookies = dict(request.cookies)

    headers.update({
        "Accept-Language": "en-US,en;q=0.9",
        "Host": f"{base_url.replace('https://', '').replace('http://', '')}",
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

    r = await client.request(
        request.method,
        f"{base_url}/{path}",
        params=params,
        headers=headers,
        cookies=cookies,
        data=data,
        stream=True,
    )
    if 'stream' in r.headers.get("Content-Type"):
        return StreamingResponse(r.aiter_content(), media_type=r.headers.get("Content-Type"))
    else:
        content = await r.atext()
        return Response(content=content, media_type=r.headers.get("content-type"), status_code=r.status_code)


if __name__ == "__main__":
    import uvicorn

    log_config = uvicorn.config.LOGGING_CONFIG
    default_format = "%(asctime)s | %(levelname)s | %(message)s"
    access_format = r'%(asctime)s | %(levelname)s | %(client_addr)s: %(request_line)s %(status_code)s'
    log_config["formatters"]["default"]["fmt"] = default_format
    log_config["formatters"]["access"]["fmt"] = access_format

    uvicorn.run("app:app", host="0.0.0.0", port=5005)
