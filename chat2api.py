import warnings

from fastapi import FastAPI, Request, Depends
from fastapi.responses import StreamingResponse, JSONResponse

from chatgpt.ChatService import ChatService
from utils.shared_session import create_shared_async_session

warnings.filterwarnings('ignore')

app = FastAPI()

oai_device_id_list = []
chat_requirements_token_list = []


@app.post("/v1/chat/completions")
async def send_conversation(request: Request, session=Depends(create_shared_async_session)):
    data = await request.json()
    chat_service = ChatService(session)
    try:
        await chat_service.get_chat_requirements()
    except:
        await chat_service.get_chat_requirements()
    chat_service.prepare_send_conversation(data)
    stream = data.get("stream", False)
    if stream:
        return StreamingResponse(chat_service.send_conversation_for_stream(data), media_type="text/event-stream")
    else:
        res = await chat_service.send_conversation(data)
        return JSONResponse(res, media_type="application/json")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("chat2api:app", host="0.0.0.0", port=5005)
