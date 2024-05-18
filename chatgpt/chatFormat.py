import asyncio
import json
import random
import string
import time
import uuid

import pybase64
import websockets

from api.files import get_file_content
from api.models import model_system_fingerprint
from api.tokens import split_tokens_from_content, calculate_image_tokens, num_tokens_from_messages
from utils.Logger import logger

moderation_message = "I'm sorry, I cannot provide or engage in any content related to pornography, violence, or any unethical material. If you have any other questions or need assistance, please feel free to let me know. I'll do my best to provide support and assistance."


async def format_not_stream_response(response, prompt_tokens, max_tokens, model):
    chat_id = f"chatcmpl-{''.join(random.choice(string.ascii_letters + string.digits) for _ in range(29))}"
    system_fingerprint_list = model_system_fingerprint.get(model, None)
    system_fingerprint = random.choice(system_fingerprint_list) if system_fingerprint_list else None
    created_time = int(time.time())
    all_text = ""
    async for chunk in response:
        try:
            if chunk.startswith("data: [DONE]"):
                break
            elif not chunk.startswith("data: "):
                continue
            else:
                chunk = json.loads(chunk[6:])
                if not chunk["choices"][0].get("delta"):
                    continue
                all_text += chunk["choices"][0]["delta"]["content"]
        except Exception as e:
            logger.error(f"Error: {chunk}, error: {str(e)}")
            continue
    content, completion_tokens, finish_reason = await split_tokens_from_content(all_text, max_tokens, model)
    message = {
        "role": "assistant",
        "content": content,
    }
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens
    }
    return {
        "id": chat_id,
        "object": "chat.completion",
        "created": created_time,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "logprobs": None,
                "finish_reason": finish_reason
            }
        ],
        "usage": usage,
        "system_fingerprint": system_fingerprint
    }


async def wss_stream_response(websocket, conversation_id):
    while not websocket.closed:
        try:
            message = await asyncio.wait_for(websocket.recv(), timeout=10)
            if message:
                resultObj = json.loads(message)
                sequenceId = resultObj.get("sequenceId", None)
                if not sequenceId:
                    continue
                data = resultObj.get("data", {})
                if conversation_id != data.get("conversation_id", ""):
                    continue
                decoded_bytes = pybase64.b64decode(data.get("body", None))
                yield decoded_bytes
            else:
                print("No message received within the specified time.")
        except asyncio.TimeoutError:
            logger.error("Timeout! No message received within the specified time.")
            break
        except websockets.ConnectionClosed as e:
            if e.code == 1000:
                logger.error("WebSocket closed normally with code 1000 (OK)")
            else:
                logger.error(f"WebSocket closed with error code {e.code}")
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            continue


async def stream_response(service, response, model, max_tokens):
    chat_id = f"chatcmpl-{''.join(random.choice(string.ascii_letters + string.digits) for _ in range(29))}"
    system_fingerprint_list = model_system_fingerprint.get(model, None)
    system_fingerprint = random.choice(system_fingerprint_list) if system_fingerprint_list else None
    created_time = int(time.time())
    completion_tokens = -1
    len_last_content = 0
    last_content_type = None
    last_recipient = None
    end = False
    message_id = None
    async for chunk in response:
        chunk = chunk.decode("utf-8")
        if end:
            yield "data: [DONE]\n\n"
            break
        try:
            if chunk.startswith("data: {"):
                chunk_old_data = json.loads(chunk[6:])
                finish_reason = None
                message = chunk_old_data.get("message", {})
                role = message.get('author', {}).get('role')
                if role == 'user':
                    continue

                conversation_id = chunk_old_data.get("conversation_id")
                status = message.get("status")
                content = message.get("content", {})
                recipient = message.get("recipient", "")
                current_message_id = message.get('id')
                if not message and chunk_old_data.get("type") == "moderation":
                    delta = {"role": "assistant", "content": moderation_message}
                    finish_reason = "stop"
                    end = True
                elif status == "in_progress":
                    outer_content_type = content.get("content_type")
                    if outer_content_type == "text":
                        part = content.get("parts", [])[0]
                        if not part:
                            message_id = message.get("id")
                            new_text = ""
                        else:
                            if message_id and message_id != message.get("id"):
                                continue
                            new_text = part[len_last_content:]
                            len_last_content = len(part)
                    else:
                        text = content.get("text", "")
                        if outer_content_type == "code" and last_content_type != "code":
                            new_text = "\n```" + recipient + "\n" + text[len_last_content:]
                        elif outer_content_type == "execution_output" and last_content_type != "execution_output":
                            new_text = "\n```" + "Output" + "\n" + text[len_last_content:]
                        else:
                            new_text = text[len_last_content:]
                        len_last_content = len(text)
                    if last_content_type == "code" and outer_content_type != "code":
                        new_text = "\n```\n" + new_text
                    elif last_content_type == "execution_output" and outer_content_type != "execution_output":
                        new_text = "\n```\n" + new_text
                    if recipient == "dalle.text2im" and last_recipient != "dalle.text2im":
                        new_text = "\n```" + "json" + "\n" + new_text
                    delta = {"content": new_text}
                    last_content_type = outer_content_type
                    last_recipient = recipient
                    if completion_tokens >= max_tokens:
                        delta = {}
                        finish_reason = "length"
                        end = True
                elif status == "finished_successfully":
                    if content.get("content_type") == "multimodal_text":
                        parts = content.get("parts", [])
                        delta = {}
                        for part in parts:
                            inner_content_type = part.get('content_type')
                            if inner_content_type == "image_asset_pointer":
                                last_content_type = "image_asset_pointer"
                                file_id = part.get('asset_pointer').replace('file-service://', '')
                                logger.debug(f"file_id: {file_id}")
                                image_download_url = await service.get_download_url(file_id)
                                logger.debug(f"image_download_url: {image_download_url}")
                                if image_download_url:
                                    delta = {"content": f"\n```\n![image]({image_download_url})\n"}
                                else:
                                    delta = {"content": f"\n```\nFailed to load the image.\n"}
                    elif not message.get("end_turn") or not message.get("metadata").get("finish_details"):
                        message_id = None
                        len_last_content = 0
                        continue
                    else:
                        part = content.get("parts", [])[0]
                        new_text = part[len_last_content:]
                        if not new_text:
                            delta = {}
                        else:
                            delta = {"content": new_text}
                        finish_reason = "stop"
                        end = True
                else:
                    continue
                if not end and not delta.get("content"):
                    delta = {"role": "assistant", "content": ""}
                chunk_new_data = {
                    "id": chat_id,
                    "object": "chat.completion.chunk",
                    "created": created_time,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": delta,
                            "logprobs": None,
                            "finish_reason": finish_reason
                        }
                    ],
                    "system_fingerprint": system_fingerprint
                }
                if not service.history_disabled:
                    chunk_new_data.update({
                        "message_id": current_message_id,
                        "conversation_id": conversation_id,
                    })
                completion_tokens += 1
                yield f"data: {json.dumps(chunk_new_data)}\n\n"
            elif chunk.startswith("data: [DONE]"):
                yield "data: [DONE]\n\n"
            else:
                continue
        except Exception as e:
            logger.error(f"Error: {chunk}, details: {str(e)}")
            continue


async def api_messages_to_chat(service, api_messages):
    file_tokens = 0
    chat_messages = []
    for api_message in api_messages:
        role = api_message.get('role')
        content = api_message.get('content')
        if isinstance(content, list):
            parts = []
            attachments = []
            content_type = "multimodal_text"
            for i in content:
                if i.get("type") == "text":
                    parts.append(i.get("text"))
                if i.get("type") == "image_url":
                    image_url = i.get("image_url")
                    url = image_url.get("url")
                    detail = image_url.get("detail", "auto")
                    file_content, mime_type = await get_file_content(url)
                    file_meta = await service.upload_file(file_content, mime_type)
                    if file_meta:
                        file_id = file_meta["file_id"]
                        file_size = file_meta["size_bytes"]
                        file_name = file_meta["file_name"]
                        mime_type = file_meta["mime_type"]
                        if mime_type.startswith("image/"):
                            width, height = file_meta["width"], file_meta["height"]
                            file_tokens += await calculate_image_tokens(width, height, detail)
                            parts.append({
                                "content_type": "image_asset_pointer",
                                "asset_pointer": f"file-service://{file_id}",
                                "size_bytes": file_size,
                                "width": width,
                                "height": height
                            })
                            attachments.append({
                                "id": file_id,
                                "size": file_size,
                                "name": file_name,
                                "mime_type": mime_type,
                                "width": width,
                                "height": height
                            })
                        else:
                            file_tokens += file_size
                            attachments.append({
                                "id": file_id,
                                "size": file_size,
                                "name": file_name,
                                "mime_type": mime_type,
                            })
            metadata = {
                "attachments": attachments
            }
        else:
            content_type = "text"
            parts = [content]
            metadata = {}
        chat_message = {
            "id": f"{uuid.uuid4()}",
            "author": {"role": role},
            "content": {"content_type": content_type, "parts": parts},
            "metadata": metadata
        }
        chat_messages.append(chat_message)
    text_tokens = await num_tokens_from_messages(api_messages, service.target_model)
    prompt_tokens = text_tokens + file_tokens
    return chat_messages, prompt_tokens
