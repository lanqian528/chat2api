from typing import AsyncGenerator

from fastapi import FastAPI, Request, Depends
from fastapi.responses import StreamingResponse, JSONResponse

from chatgpt.ChatService import ChatService
from utils.authorization import verify_token
from utils.retry import async_retry

app = FastAPI()


@app.post("/v1/chat/completions")
async def send_conversation(request: Request, token=Depends(verify_token)):
    access_token = None
    if not token:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    elif token.startswith("ey"):
        access_token = token
    try:
        request_data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    async def to_send_conversation(request_data):
        chat_service = ChatService(request_data, access_token)
        await chat_service.get_chat_requirements()
        return chat_service

    chat_service = await async_retry(to_send_conversation, request_data)
    chat_service.prepare_send_conversation()
    stream = request_data.get("stream", False)
    if stream:
        return StreamingResponse(await chat_service.send_conversation_for_stream(), media_type="text/event-stream")
    else:
        return JSONResponse(await chat_service.send_conversation(), media_type="application/json")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5005)
