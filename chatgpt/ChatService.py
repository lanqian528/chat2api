import json
import random
import string
import time
import uuid

import httpx
from fastapi import HTTPException

from api.chat_completions import num_tokens_from_messages, model_system_fingerprint, model_proxy, \
    split_tokens_from_content
from utils.Logger import Logger
from utils.config import chatgpt_base_url, history_disabled, proxy_url


async def stream_response(response, model, max_tokens):
    chat_id = f"chatcmpl-{''.join(random.choice(string.ascii_letters + string.digits) for _ in range(29))}"
    system_fingerprint_list = model_system_fingerprint.get(model, None)
    system_fingerprint = random.choice(system_fingerprint_list) if system_fingerprint_list else None
    created_time = int(time.time())
    completion_tokens = -1
    len_last_content = 0
    end = False
    async for chunk in response.aiter_lines():
        if end:
            yield f"data: [DONE]\n\n"
            break
        try:
            if chunk == "data: [DONE]":
                yield f"data: [DONE]\n\n"
            elif not chunk.startswith("data: "):
                continue
            else:
                chunk_old_data = json.loads(chunk[6:])
                if not chunk_old_data["message"]["status"] == "in_progress" and not chunk_old_data["message"]["metadata"].get("finish_details", {}):
                    continue
                content = chunk_old_data["message"]["content"]["parts"][0]
                if not content:
                    delta = {"role": "assistant", "content": ""}
                else:
                    delta = {"content": content[len_last_content:]}
                len_last_content = len(content)
                finish_reason = None
                if chunk_old_data["message"]["metadata"].get("finish_details", {}):
                    delta = {}
                    finish_reason = "stop"
                    end = True
                if completion_tokens == max_tokens:
                    delta = {}
                    finish_reason = "length"
                    end = True
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
                completion_tokens += 1
                yield f"data: {json.dumps(chunk_new_data)}\n\n"
        except Exception as e:
            Logger.error(f"Error: {str(e)}")
            Logger.error(f"Error: {chunk}")
            continue


async def chat_response(resp, model, prompt_tokens, max_tokens):
    last_resp = None
    for i in reversed(resp):
        if i != "" and i != "data: [DONE]" and i.startswith("data: "):
            last_resp = i
            break
    resp = json.loads(last_resp[6:])

    chat_id = f"chatcmpl-{''.join(random.choice(string.ascii_letters + string.digits) for _ in range(29))}"
    chat_object = "chat.completion"
    created_time = int(time.time())
    index = 0
    message_content = resp["message"]["content"]["parts"][0]
    message_content, completion_tokens, finish_reason = split_tokens_from_content(message_content, max_tokens, model)
    message = {
        "role": "assistant",
        "content": message_content,

    }
    logprobs = None
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens
    }
    system_fingerprint_list = model_system_fingerprint.get(model, None)
    system_fingerprint = random.choice(system_fingerprint_list) if system_fingerprint_list else None
    chat_response_json = {
        "id": chat_id,
        "object": chat_object,
        "created": created_time,
        "model": model,
        "choices": [
            {
                "index": index,
                "message": message,
                "logprobs": logprobs,
                "finish_reason": finish_reason
            }
        ],
        "usage": usage,
        "system_fingerprint": system_fingerprint
    }
    return chat_response_json


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


class ChatService:
    def __init__(self, session=None):
        self.s = httpx.AsyncClient(proxies=proxy_url)
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/"
        self.oai_device_id = str(uuid.uuid4())
        self.chat_token = None

        self.headers = None
        self.chat_request = None

    async def get_chat_requirements(self):
        url = f'{chatgpt_base_url}/sentinel/chat-requirements'
        headers = {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'application/json',
            'oai-device-id': self.oai_device_id,
            'oai-language': 'en-US',
            'origin': 'https://chat.openai.com',
            'referer': 'https://chat.openai.com/',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.user_agent
        }
        r = await self.s.post(url, headers=headers, json={})
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        else:
            self.chat_token = r.json().get('token')
            if not self.chat_token:
                raise HTTPException(status_code=500, detail="Chat token not found")
            return self.chat_token

    def prepare_send_conversation(self, data):
        self.headers = {
            'Accept': 'text/event-stream',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'en-US,en;q=0.9',
            'Content-Type': 'application/json',
            'Oai-Device-Id': self.oai_device_id,
            'Oai-Language': 'en-US',
            'Openai-Sentinel-Chat-Requirements-Token': self.chat_token,
            'Origin': 'https://chat.openai.com',
            'Referer': 'https://chat.openai.com/',
            'Sec-Ch-Ua': '"Microsoft Edge";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': self.user_agent
        }
        api_messages = data.get("messages", [])
        chat_messages = api_messages_to_chat(api_messages)
        model = "text-davinci-002-render-sha"
        parent_message_id = f"{uuid.uuid4()}"
        self.chat_request = {
            "action": "next",
            "messages": chat_messages,
            "parent_message_id": parent_message_id,
            "model": model,
            "timezone_offset_min": -480,
            "suggestions": [],
            "history_and_training_disabled": history_disabled,
            "conversation_mode": {"kind": "primary_assistant"},
            "force_paragen": False,
            "force_paragen_model_slug": "",
            "force_nulligen": False,
            "force_rate_limit": False,
        }

    async def send_conversation_for_stream(self, data):
        url = f'{chatgpt_base_url}/conversation'
        model = data.get("model", "gpt-3.5-turbo-0125")
        model = model_proxy.get(model, model)
        max_tokens = data.get("max_tokens", 2147483647)

        r = await self.s.send(
            self.s.build_request("POST", url, headers=self.headers, json=self.chat_request, timeout=600), stream=True)
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        async for chunk in stream_response(r, model, max_tokens):
            yield chunk

    async def send_conversation(self, data):
        url = f'{chatgpt_base_url}/conversation'
        model = data.get("model", "gpt-3.5-turbo-0125")
        model = model_proxy.get(model, model)
        api_messages = data.get("messages", [])
        prompt_tokens = num_tokens_from_messages(api_messages, model)
        max_tokens = data.get("max_tokens", 2147483647)

        r = await self.s.send(
            self.s.build_request("POST", url, headers=self.headers, json=self.chat_request, timeout=600), stream=False)
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        resp = r.text.split("\n")
        return await chat_response(resp, model, prompt_tokens, max_tokens)
