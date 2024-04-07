from fastapi import FastAPI, Request, Depends
from fastapi.responses import StreamingResponse, JSONResponse

from chatgpt.ChatService import ChatService
from utils.authorization import verify_token
from utils.retry import async_retry

app = FastAPI()

oai_device_id_list = []
chat_requirements_token_list = []


@app.post("/v1/chat/completions")
async def send_conversation(request: Request, verified: bool = Depends(verify_token)):
    if not verified:
        return JSONResponse({"error": "Invalid token"}, status_code=401)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    async def to_send_conversation(data):
        chat_service = ChatService()
        await chat_service.get_chat_requirements()
        return chat_service

    chat_service = await async_retry(to_send_conversation, data)
    chat_service.prepare_send_conversation(data)
    stream = data.get("stream", False)
    if stream:
        return StreamingResponse(chat_service.send_conversation_for_stream(data), media_type="text/event-stream")
    else:
        return JSONResponse(await chat_service.send_conversation(data), media_type="application/json")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=5005)
