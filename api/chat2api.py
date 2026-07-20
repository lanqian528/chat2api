import asyncio
import time
import types
import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Request, HTTPException, Form, Security
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from starlette.background import BackgroundTask

import utils.globals as globals
from app import app, templates, security_scheme
from chatgpt.ChatService import ChatService
from chatgpt.authorization import refresh_all_tokens
from chatgpt import session_sticky
from utils.bootstrap import initialize_from_env
from utils.Logger import logger
from utils.configs import api_prefix, scheduled_refresh, history_disabled, enable_session_sticky
from utils.retry import async_retry
from utils import antiban
from utils.antiban import circuit as antiban_circuit

scheduler = AsyncIOScheduler()


def _responses_input_to_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        chunks = []
        for item in value:
            if isinstance(item, str):
                chunks.append(item)
                continue
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type in {"input_text", "output_text", "text"}:
                text = item.get("text")
                if isinstance(text, str):
                    chunks.append(text)
            elif item_type == "message":
                chunks.append(_responses_input_to_messages(item))
        return "\n".join(part for part in chunks if part)
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        if isinstance(value.get("content"), list):
            return _responses_input_to_text(value["content"])
    return str(value)


def _responses_input_to_messages(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        role = value.get("role")
        if role in {"system", "developer", "user", "assistant"}:
            content = _responses_input_to_text(value.get("content"))
            return {"role": role, "content": content or ""}
    return None


def _convert_responses_request_to_chat(payload):
    messages = []
    instructions = payload.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        messages.append({"role": "system", "content": instructions.strip()})

    raw_input = payload.get("input")
    if isinstance(raw_input, str):
        messages.append({"role": "user", "content": raw_input})
    elif isinstance(raw_input, list):
        for item in raw_input:
            message = _responses_input_to_messages(item)
            if message:
                messages.append(message)
            else:
                text = _responses_input_to_text(item)
                if text:
                    messages.append({"role": "user", "content": text})
    elif raw_input is not None:
        text = _responses_input_to_text(raw_input)
        if text:
            messages.append({"role": "user", "content": text})

    if not messages:
        raise HTTPException(status_code=400, detail={"error": "input is required"})

    chat_payload = {
        "model": payload.get("model"),
        "messages": messages,
        "stream": bool(payload.get("stream", False)),
    }
    for key in (
        "temperature",
        "top_p",
        "max_output_tokens",
        "presence_penalty",
        "frequency_penalty",
        "user",
    ):
        if key in payload:
            value = payload[key]
            if key == "max_output_tokens":
                chat_payload["max_tokens"] = value
            else:
                chat_payload[key] = value
    return chat_payload


def _convert_chat_response_to_responses(chat_response, request_payload):
    choice = ((chat_response or {}).get("choices") or [{}])[0]
    message = choice.get("message") or {}
    output_text = message.get("content", "") or ""
    usage = chat_response.get("usage") or {}
    created = int(time.time())
    response_id = f"resp_{uuid.uuid4().hex}"
    model = chat_response.get("model") or request_payload.get("model")
    return {
        "id": response_id,
        "object": "response",
        "created_at": created,
        "status": "completed",
        "model": model,
        "output": [
            {
                "id": f"msg_{uuid.uuid4().hex}",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": output_text,
                        "annotations": [],
                    }
                ],
            }
        ],
        "output_text": output_text,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
        "finish_reason": choice.get("finish_reason"),
    }


def _compact_responses_payload(data):
    usage = data.get("usage") or {}
    return {
        "id": data.get("id"),
        "object": "response.compact",
        "model": data.get("model"),
        "output_text": data.get("output_text", ""),
        "finish_reason": data.get("finish_reason"),
        "usage": usage,
    }


async def _process_responses_request(request_data, req_token):
    chat_request_data = _convert_responses_request_to_chat(request_data)
    if chat_request_data.get("stream"):
        raise HTTPException(status_code=400, detail={"error": "stream responses is not supported yet"})

    chat_service, res = await async_retry(process, chat_request_data, req_token)
    try:
        if isinstance(res, types.AsyncGeneratorType):
            raise HTTPException(status_code=400, detail={"error": "stream responses is not supported yet"})
        return _convert_chat_response_to_responses(res, request_data)
    finally:
        await chat_service.close_client()


@app.on_event("startup")
async def app_start():
    initialize_from_env()
    await antiban.init()

    # Session sticky: 启动时初始化 SQLite + 启动 TTL 清理定时任务
    if enable_session_sticky:
        session_sticky.init_db()
        scheduler.add_job(
            id='session_sticky_cleanup',
            func=session_sticky.cleanup_expired,
            trigger='interval',
            hours=24,
        )

    # Antiban 自愈定时任务
    from utils.configs import enable_antiban, circuit_bucket_heal_minutes
    if enable_antiban:
        scheduler.add_job(
            id='antiban_heal',
            func=antiban_circuit.scheduled_heal,
            trigger='interval',
            minutes=max(int(circuit_bucket_heal_minutes), 5),
        )

    if scheduled_refresh:
        scheduler.add_job(id='refresh', func=refresh_all_tokens, trigger='cron', hour=3, minute=0, day='*/2',
                          kwargs={'force_refresh': True})
        scheduler.start()
        asyncio.get_event_loop().call_later(0, lambda: asyncio.create_task(refresh_all_tokens(force_refresh=False)))
    elif enable_antiban:
        # 只有 antiban 启用、没启用 refresh 时，也需要把 scheduler 跑起来
        scheduler.start()
    elif enable_session_sticky:
        # 仅 session_sticky 启用时，scheduler 也要启动以执行 cleanup
        scheduler.start()


async def to_send_conversation(request_data, req_token):
    chat_service = ChatService(req_token)
    try:
        await chat_service.set_dynamic_data(request_data)
        await chat_service.get_chat_requirements()
        return chat_service
    except HTTPException as e:
        await chat_service.close_client()
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        await chat_service.close_client()
        logger.error(f"Server error, {str(e)}")
        raise HTTPException(status_code=500, detail="Server error")


async def process(request_data, req_token):
    chat_service = await to_send_conversation(request_data, req_token)
    try:
        await chat_service.prepare_send_conversation()
        res = await chat_service.send_conversation()
        return chat_service, res
    except HTTPException as e:
        await chat_service.close_client()
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        await chat_service.close_client()
        logger.error(f"Server error, {str(e)}")
        raise HTTPException(status_code=500, detail="Server error")


def parse_bool_query(value, default):
    if value is None:
        return default
    return str(value).lower() in ['true', '1', 't', 'y', 'yes']


def format_models_response(model_slugs):
    data = []
    for model_slug in sorted(model_slugs):
        data.append({
            "id": model_slug,
            "object": "model",
            "created": 0,
            "owned_by": "openai",
        })
    return {
        "object": "list",
        "data": data,
    }


@app.post(f"/{api_prefix}/v1/chat/completions" if api_prefix else "/v1/chat/completions")
async def send_conversation(request: Request, credentials: HTTPAuthorizationCredentials = Security(security_scheme)):
    req_token = credentials.credentials
    try:
        request_data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail={"error": "Invalid JSON body"})
    # Session sticky: LibreChat conv_id → ChatGPT conv_id 翻译注入
    # 副作用: 命中映射时改写 request_data['conversation_id'/'parent_message_id'/'messages']
    # 返回 lc_conv_id 用于流式响应嗅探回写；未启用或无 lc 字段时返回 None
    lc_conv_id = session_sticky.inject_session(request_data) if enable_session_sticky else None
    chat_service, res = await async_retry(process, request_data, req_token)
    # 把 lc_conv_id 挂到 chat_service 上，供 stream_response 嗅探时回写 DB
    if lc_conv_id:
        chat_service.librechat_conv_id = lc_conv_id
    try:
        if isinstance(res, types.AsyncGeneratorType):
            background = BackgroundTask(chat_service.close_client)
            return StreamingResponse(res, media_type="text/event-stream", background=background)
        else:
            background = BackgroundTask(chat_service.close_client)
            return JSONResponse(res, media_type="application/json", background=background)
    except HTTPException as e:
        await chat_service.close_client()
        if e.status_code == 500:
            logger.error(f"Server error, {str(e)}")
            raise HTTPException(status_code=500, detail="Server error")
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        await chat_service.close_client()
        logger.error(f"Server error, {str(e)}")
        raise HTTPException(status_code=500, detail="Server error")


@app.post(f"/{api_prefix}/v1/responses" if api_prefix else "/v1/responses")
async def send_responses(request: Request, credentials: HTTPAuthorizationCredentials = Security(security_scheme)):
    req_token = credentials.credentials
    try:
        request_data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail={"error": "Invalid JSON body"})
    try:
        response_payload = await _process_responses_request(request_data, req_token)
        return JSONResponse(response_payload, media_type="application/json")
    except HTTPException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.error(f"Server error, {str(e)}")
        raise HTTPException(status_code=500, detail="Server error")


@app.post(f"/{api_prefix}/v1/responses/compact" if api_prefix else "/v1/responses/compact")
async def send_responses_compact(request: Request, credentials: HTTPAuthorizationCredentials = Security(security_scheme)):
    req_token = credentials.credentials
    try:
        request_data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail={"error": "Invalid JSON body"})
    try:
        data = await _process_responses_request(request_data, req_token)
        return JSONResponse(_compact_responses_payload(data), media_type="application/json")
    except HTTPException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.error(f"Server error, {str(e)}")
        raise HTTPException(status_code=500, detail="Server error")

@app.get(f"/{api_prefix}/v1/models" if api_prefix else "/v1/models")
async def list_models(request: Request, credentials: HTTPAuthorizationCredentials = Security(security_scheme)):
    chat_service = ChatService(credentials.credentials)
    try:
        await chat_service.resolve_auth_context()
        chat_service.history_disabled = parse_bool_query(
            request.query_params.get("history_disabled", request.query_params.get("history_and_training_disabled")),
            history_disabled,
        )
        request_account_id = request.headers.get("ChatGPT-Account-ID") or request.headers.get("Chatgpt-Account-Id")
        if request_account_id:
            chat_service.account_id = request_account_id
        await chat_service.initialize_request_context()
        model_slugs = await chat_service.fetch_available_models()
        return JSONResponse(format_models_response(model_slugs), media_type="application/json")
    except HTTPException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.error(f"Server error, {str(e)}")
        raise HTTPException(status_code=500, detail="Server error")
    finally:
        await chat_service.close_client()


@app.get(f"/{api_prefix}/tokens" if api_prefix else "/tokens", response_class=HTMLResponse)
async def upload_html(request: Request):
    tokens_count = len(set(globals.token_list) - set(globals.error_token_list))
    return templates.TemplateResponse("tokens.html",
                                      {"request": request, "api_prefix": api_prefix, "tokens_count": tokens_count})


@app.post(f"/{api_prefix}/tokens/upload" if api_prefix else "/tokens/upload")
async def upload_post(text: str = Form(...)):
    lines = text.split("\n")
    for line in lines:
        if line.strip() and not line.startswith("#"):
            globals.token_list.append(line.strip())
            with open(globals.TOKENS_FILE, "a", encoding="utf-8") as f:
                f.write(line.strip() + "\n")
    logger.info(f"Token count: {len(globals.token_list)}, Error token count: {len(globals.error_token_list)}")
    tokens_count = len(set(globals.token_list) - set(globals.error_token_list))
    return {"status": "success", "tokens_count": tokens_count}


@app.post(f"/{api_prefix}/tokens/clear" if api_prefix else "/tokens/clear")
async def clear_tokens():
    globals.token_list.clear()
    globals.error_token_list.clear()
    with open(globals.TOKENS_FILE, "w", encoding="utf-8") as f:
        pass
    logger.info(f"Token count: {len(globals.token_list)}, Error token count: {len(globals.error_token_list)}")
    tokens_count = len(set(globals.token_list) - set(globals.error_token_list))
    return {"status": "success", "tokens_count": tokens_count}


@app.post(f"/{api_prefix}/tokens/error" if api_prefix else "/tokens/error")
async def error_tokens():
    error_tokens_list = list(set(globals.error_token_list))
    return {"status": "success", "error_tokens": error_tokens_list}


@app.get(f"/{api_prefix}/tokens/add/{{token}}" if api_prefix else "/tokens/add/{token}")
async def add_token(token: str):
    if token.strip() and not token.startswith("#"):
        globals.token_list.append(token.strip())
        with open(globals.TOKENS_FILE, "a", encoding="utf-8") as f:
            f.write(token.strip() + "\n")
    logger.info(f"Token count: {len(globals.token_list)}, Error token count: {len(globals.error_token_list)}")
    tokens_count = len(set(globals.token_list) - set(globals.error_token_list))
    return {"status": "success", "tokens_count": tokens_count}


@app.post(f"/{api_prefix}/seed_tokens/clear" if api_prefix else "/seed_tokens/clear")
async def clear_seed_tokens():
    globals.seed_map.clear()
    globals.conversation_map.clear()
    with open(globals.SEED_MAP_FILE, "w", encoding="utf-8") as f:
        f.write("{}")
    with open(globals.CONVERSATION_MAP_FILE, "w", encoding="utf-8") as f:
        f.write("{}")
    logger.info(f"Seed token count: {len(globals.seed_map)}")
    return {"status": "success", "seed_tokens_count": len(globals.seed_map)}
