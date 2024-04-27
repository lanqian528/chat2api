import asyncio
import base64
import json
import random
import string
import time
import uuid
import traceback

from api.chat_completions import model_system_fingerprint, split_tokens_from_content
from utils.Logger import Logger

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
            Logger.error(f"Error: {chunk}, error: {str(e)}")
            continue
    content, completion_tokens, finish_reason = split_tokens_from_content(all_text, max_tokens, model)
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


async def wss_stream_response(websocket):
    while True:
        try:
            message = await asyncio.wait_for(websocket.recv(), timeout=15)
            print(f"message:{message}")
            if message:
                resultObj = json.loads(message)
                sequenceId = resultObj.get("sequenceId", None)
                if not sequenceId:
                    continue
                result = resultObj.get("data", {}).get("body", None)
                decoded_bytes = base64.b64decode(result)
                print(f"decoded_bytes:{decoded_bytes}")
                yield decoded_bytes
            else:
                continue
        except asyncio.TimeoutError:
            Logger.error("Timeout! No message received within the specified time.")
            break
        except Exception as e:
            Logger.error(f"Error: {str(e)}")
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
            if chunk.startswith("data: [DONE]"):
                yield "data: [DONE]\n\n"
            elif not chunk.startswith("data: {"):
                continue
            else:
                chunk_old_data = json.loads(chunk[6:])
                finish_reason = None
                message = chunk_old_data.get("message", {})
                role = message.get('author', {}).get('role')
                if role == 'user':
                    continue
                status = message.get("status")
                content = message.get("content", {})
                recipient = message.get("recipient", "")
                current_message_id = message.get('id')
                conversation_id = chunk_old_data.get('conversation_id')
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
                                asset_pointer = part.get('asset_pointer').replace('file-service://', '')
                                Logger.debug(f"asset_pointer: {asset_pointer}")
                                image_download_url = await service.get_image_download_url(asset_pointer)
                                Logger.debug(f"image_download_url: {image_download_url}")
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
        except Exception as e:
            Logger.error(f"Error: {chunk}, details: {str(e)}")
            continue


def api_messages_to_chat(api_messages):
    chat_messages = []
    for api_message in api_messages:
        role = api_message.get('role')
        content = api_message.get('content')
        chat_message = {
            "id": f"{uuid.uuid4()}",
            "author": {"role": role},
            "content": {"content_type": "text", "parts": [content]},
            "metadata": {}
        }
        chat_messages.append(chat_message)
    return chat_messages
