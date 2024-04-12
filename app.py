from fastapi import FastAPI, Request, Depends, HTTPException
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
    if token and token.startswith("eyJhbGciOi"):
        access_token = token

    # 入参格式校验
    try:
        request_data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail={"error": "Invalid JSON body"})

    # 对话前先决条件准备
    chat_service = await async_retry(to_send_conversation, request_data, access_token)
    chat_service.prepare_send_conversation()

    # 发送对话
    stream = request_data.get("stream", False)
    if stream is True:
        return StreamingResponse(await chat_service.send_conversation_for_stream(), media_type="text/event-stream")
    else:
        return JSONResponse(await chat_service.send_conversation(), media_type="application/json")


if __name__ == "__main__":
    import uvicorn

    log_config = uvicorn.config.LOGGING_CONFIG
    default_format = "%(asctime)s | %(levelname)s | %(message)s"
    access_format = r'%(asctime)s | %(levelname)s | %(client_addr)s: %(request_line)s %(status_code)s'
    log_config["formatters"]["default"]["fmt"] = default_format
    log_config["formatters"]["access"]["fmt"] = access_format

    uvicorn.run("app:app", host="0.0.0.0", port=5005)
