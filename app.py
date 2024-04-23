import types

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

from chatgpt.ChatService import ChatService
from chatgpt.reverseProxy import chatgpt_reverse_proxy
from utils.authorization import verify_token
from utils.retry import async_retry

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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

    res = await chat_service.send_conversation()
    if isinstance(res, types.AsyncGeneratorType):
        return StreamingResponse(res, media_type="text/event-stream")
    else:
        return JSONResponse(res, media_type="application/json")


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH", "TRACE"])
async def reverse_proxy(request: Request, path: str):
    return await chatgpt_reverse_proxy(request, path)


if __name__ == "__main__":
    import uvicorn

    log_config = uvicorn.config.LOGGING_CONFIG
    default_format = "%(asctime)s | %(levelname)s | %(message)s"
    access_format = r'%(asctime)s | %(levelname)s | %(client_addr)s: %(request_line)s %(status_code)s'
    log_config["formatters"]["default"]["fmt"] = default_format
    log_config["formatters"]["access"]["fmt"] = access_format

    uvicorn.run("app:app", host="0.0.0.0", port=5005)
