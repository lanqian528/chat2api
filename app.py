from fastapi import FastAPI, Request, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from chatgpt.ChatService import ChatService
from utils.authorization import verify_token
from utils.retry import async_retry

app = FastAPI()


async def to_send_conversation(request_data, access_token):
    """
    对话前先决条件准备
    :param request_data: 请求数据
    :param access_token: 访问令牌
    :return: chat_service
    """
    chat_service = ChatService(request_data, access_token)
    await chat_service.get_chat_requirements()
    return chat_service


@app.post("/v1/chat/completions")
async def send_conversation(request: Request, token=Depends(verify_token)):
    """
    发送对话
    :param request: 请求入参
    :param token: 访问令牌
    :return: 对话结果
    """
    access_token = None
    if token and token.startswith("ey"):
        access_token = token

    # 入参格式校验
    try:
        request_data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    # 对话前先决条件准备
    chat_service = await async_retry(to_send_conversation, request_data, access_token)
    chat_service.prepare_send_conversation()

    # 发送对话
    stream = request_data.get("stream", False)
    if stream:
        # 流式响应
        return StreamingResponse(await chat_service.send_conversation_for_stream(), media_type="text/event-stream")
    else:
        # 非流式响应
        return JSONResponse(await chat_service.send_conversation(), media_type="application/json")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5005)
