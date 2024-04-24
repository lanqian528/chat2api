import json
import random
import string
import time
import uuid
import websockets
import asyncio
import base64

from fastapi import HTTPException

from api.chat_completions import num_tokens_from_messages, model_system_fingerprint, model_proxy, num_tokens_from_content
from chatgpt.proofofwork import calc_proof_token
from utils.Client import Client
from utils.Logger import Logger
from utils.config import proxy_url_list, chatgpt_base_url_list, arkose_token_url_list

moderation_message = "I'm sorry, I cannot provide or engage in any content related to pornography, violence, or any unethical material. If you have any other questions or need assistance, please feel free to let me know. I'll do my best to provide support and assistance."


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
    current_message_id = None
    conversation_id = None
    all_text = ""
    async for chunk in response:
        chunk = chunk.decode("utf-8")
        print(f"chunk:{chunk}")
        if end:
            yield "data: [DONE]\n\n"
            break
        try:
            # to ignore afterwards \n\n for websocket message.
            if chunk.startswith("data: [DONE]"):
                yield "data: [DONE]\n\n"
            elif not chunk.startswith("data: "):
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
                            # for wss message, first valid text, message_id is None
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
                        delta = {}
                        finish_reason = "stop"
                        end = True
                else:
                    continue
                if not delta.get("content"):
                    delta = {"role": "assistant", "content": ""}
                chunk_new_data = {
                    "id": chat_id,
                    "message_id": current_message_id,
                    "conversation_id": conversation_id,
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
                print(f'chunk_new_data:{chunk_new_data}')
                yield f"data: {json.dumps(chunk_new_data)}\n\n"
        except Exception as e:
            Logger.error(f"Error: {chunk}, error: {str(e)}")
            continue


async def chat_response(service, response, prompt_tokens, model, max_tokens):
    chat_id = f"chatcmpl-{''.join(random.choice(string.ascii_letters + string.digits) for _ in range(29))}"
    system_fingerprint_list = model_system_fingerprint.get(model, None)
    system_fingerprint = random.choice(system_fingerprint_list) if system_fingerprint_list else None
    created_time = int(time.time())
    finish_reason = "stop"
    completion_tokens = -1
    len_last_content = 0
    last_content_type = None
    last_recipient = None
    end = False
    message_id = None
    all_text = ""
    async for chunk in response.aiter_lines():
        chunk = chunk.decode("utf-8")
        if end:
            break
        try:
            if chunk.startswith("data: [DONE]"): # ignore afterwards \n\n for websocket.
                break
            elif not chunk.startswith("data: "):
                continue
            else:
                chunk_old_data = json.loads(chunk[6:])
                finish_reason = None
                message = chunk_old_data.get("message", {})
                status = message.get("status")
                content = message.get("content", {})
                recipient = message.get("recipient", "")
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
                            if message_id != message.get("id"):
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
                        delta = {}
                        finish_reason = "stop"
                        end = True
                else:
                    continue
                all_text += delta.get("content", "")
                completion_tokens += 1
        except Exception as e:
            Logger.error(f"Error: {chunk}, error: {str(e)}")
            continue

    completion_tokens = num_tokens_from_content(all_text, model)
    message = {
        "role": "assistant",
        "content": all_text,
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
    def __init__(self, data, access_token=None):
        self.proxy_url = random.choice(proxy_url_list) if proxy_url_list else None
        self.s = Client(proxy=self.proxy_url)
        if access_token:
            self.base_url = random.choice(chatgpt_base_url_list) + "/backend-api"
        else:
            self.base_url = random.choice(chatgpt_base_url_list) + "/backend-anon"
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0"

        self.access_token = access_token
        self.oai_device_id = str(uuid.uuid4())
        self.persona = None
        self.chat_token = None
        self.arkose_token = None
        self.arkose_token_url = random.choice(arkose_token_url_list) if arkose_token_url_list else None
        self.proof_token = None

        self.data = data
        self.model = self.data.get("model", "gpt-3.5-turbo-0125")
        self.api_messages = self.data.get("messages", [])
        self.prompt_tokens = num_tokens_from_messages(self.api_messages, self.model)
        self.max_tokens = self.data.get("max_tokens", 2147483647)

        self.headers = None
        self.chat_request = None

    async def get_chat_requirements(self):
        url = f'{self.base_url}/sentinel/chat-requirements'
        headers = {
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Content-Type': 'application/json',
            'Oai-Device-Id': self.oai_device_id,
            'Oai-Language': 'en-US',
            'Origin': 'https://chat.openai.com',
            'Referer': 'https://chat.openai.com/',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': self.user_agent
        }
        if self.access_token:
            headers['Authorization'] = f'Bearer {self.access_token}'
        try:
            r = await self.s.post(url, headers=headers, json={})
            if r.status_code == 200:
                resp = r.json()
                self.persona = resp.get("persona")
                arkose = resp.get('arkose', {})
                proofofwork = resp.get('proofofwork', {})
                turnstile = resp.get('turnstile', {})
                arkose_required = arkose.get('required')
                if arkose_required:
                    if not self.arkose_token_url:
                        raise HTTPException(status_code=403, detail="Arkose service required")
                    arkose_dx = arkose.get("dx")
                    arkose_client = Client()
                    try:
                        r2 = await arkose_client.post(
                            url=self.arkose_token_url,
                            json={"blob": arkose_dx},
                            timeout=15
                        )
                        r2esp = r2.json()
                        Logger.info(f"arkose_token: {r2esp}")
                        self.arkose_token = r2esp.get('token')
                    except Exception:
                        raise HTTPException(status_code=403, detail="Failed to get Arkose token")

                proofofwork_required = proofofwork.get('required')
                if proofofwork_required:
                    proofofwork_seed = proofofwork.get("seed")
                    proofofwork_diff = proofofwork.get("difficulty")
                    self.proof_token = calc_proof_token(proofofwork_seed, proofofwork_diff)

                turnstile_required = turnstile.get('required')
                if turnstile_required:
                    raise HTTPException(status_code=403, detail="Turnstile required")

                self.chat_token = resp.get('token')
                if not self.chat_token:
                    raise HTTPException(status_code=502, detail=f"Failed to get chat token: {r.text}")
                return self.chat_token
            else:
                if "application/json" == r.headers.get("Content-Type", ""):
                    detail = r.json().get("detail", r.json())
                else:
                    detail = r.content

                if r.status_code == 403:
                    raise HTTPException(status_code=r.status_code, detail="cf-please-wait")
                elif r.status_code == 429:
                    raise HTTPException(status_code=r.status_code, detail="rate-limit")
                raise HTTPException(status_code=r.status_code, detail=detail)

        except HTTPException as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def prepare_send_conversation(self, parent_message_id=None, conversation_id=None, history_disabled=True):
        self.headers = {
            'Accept': 'text/event-stream',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'en-US,en;q=0.9',
            'Content-Type': 'application/json',
            'Oai-Device-Id': self.oai_device_id,
            'Oai-Language': 'en-US',
            'Openai-Sentinel-Chat-Requirements-Token': self.chat_token,
            'Openai-Sentinel-Proof-Token': self.proof_token,
            'Openai-Sentinel-Arkose-Token': self.arkose_token,
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
        if self.access_token:
            self.headers['Authorization'] = f'Bearer {self.access_token}'
        chat_messages = api_messages_to_chat(self.api_messages)
        if "gpt-4" in self.data.get("model"):
            model = "gpt-4"
        else:
            model = "text-davinci-002-render-sha"
        parent_message_id = parent_message_id if parent_message_id else f"{uuid.uuid4()}"
        print(f"input conversation_id: {conversation_id}")
        websocket_request_id = f"{uuid.uuid4()}"
        self.chat_request = {
            "action": "next",
            "messages": chat_messages,
            "parent_message_id": parent_message_id,
            "model": model,
            "timezone_offset_min": -480,
            "suggestions": [],
            # let user decide whether or not we need to keep conversation history.
            "history_and_training_disabled": history_disabled,
            "conversation_mode": {"kind": "primary_assistant"},
            "force_paragen": False,
            "force_paragen_model_slug": "",
            "force_nulligen": False,
            "force_rate_limit": False,
            "websocket_request_id": websocket_request_id,
        }
        if conversation_id:
            self.chat_request['conversation_id'] = conversation_id
        print(f"chat_request:{self.chat_request}", flush=True)
        return self.chat_request

    async def wss_response_stream(self, detail):
        wss_url = detail.get('wss_url')
        subprotocols = ["json.reliable.webpubsub.azure.v1"]
        async with websockets.connect(wss_url, ping_interval=None, subprotocols=subprotocols) as websocket:
            while True:
                message = None
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=30)
                    if message:
                        # print(f'wss messsage:{message}')
                        resultObj = json.loads(message)
                        sequenceId = resultObj.get("sequenceId", None)
                        if not sequenceId:
                            continue
                        result = resultObj.get("data", {}).get("body", None)
                        # {"type": "http.response.body", "body": "ZGF0YTogeyJjb252ZXJzYXRpb25faWQiOiAiNDJhNjNiNWItNDVhZC00Nzg0LWIwNGMtZWNlMDIyNDZhY2Q4IiwgIm1lc3NhZ2VfaWQiOiAiZGNiMTUxM2ItZmU1NC00ZWM5LWJiY2MtZmRhYTJkZWRhMzI0IiwgImlzX2NvbXBsZXRpb24iOiB0cnVlLCAibW9kZXJhdGlvbl9yZXNwb25zZSI6IHsiZmxhZ2dlZCI6IGZhbHNlLCAiYmxvY2tlZCI6IGZhbHNlLCAibW9kZXJhdGlvbl9pZCI6ICJtb2RyLThublA5UGpZVEZLUHl6Z0hDRlFtNHZTOUNESTU1In19Cgo=", "more_body": true, "response_id": "84f29a22d9ac8c4b-EWR", "conversation_id": "42a63b5b-45ad-4784-b04c-ece02246acd8"}
                        decoded_bytes = base64.b64decode(result)
                        # result = decoded_bytes.decode("utf-8")
                        yield decoded_bytes
                    else:
                        return
                    # print(f"Message from server: {message}")
                except asyncio.TimeoutError:
                    # Handle timeout, e.g., by breaking the loop or doing something else
                    print("Timeout! No message received within the specified time.")
                    return

    async def send_conversation(self):
        url = f'{self.base_url}/conversation'
        # Check for model access or existence
        if "gpt-4" in self.model and self.persona != "chatgpt-paid":
            raise HTTPException(status_code=404, detail={
                "message": f"The model `{self.model}` does not exist or you do not have access to it.",
                "type": "invalid_request_error",
                "param": None,
                "code": "model_not_found"
            })
        model = model_proxy.get(self.model, self.model)
        try:
            stream = self.data.get("stream", False)
            r = await self.s.post(url, headers=self.headers, json=self.chat_request, timeout=600, stream=True)
            if r.status_code != 200:
                if r.status_code == 403:
                    detail = "cf-please-wait"
                else:
                    rtext = await r.atext()
                    detail = json.loads(rtext).get("detail", rtext)
                raise HTTPException(status_code=r.status_code, detail=detail)

            content_type = r.headers.get("Content-Type", "")
            if "text/event-stream" in content_type and stream:
                return stream_response(self, r.aiter_lines(), model, self.max_tokens)
            elif "application/json" in content_type:
                rtext = await r.atext()
                detail = json.loads(rtext).get("detail", json.loads(rtext))
                if stream:
                    print(f"detail: {detail}", flush=True)
                    wss_r = self.wss_response_stream(detail)
                    return stream_response(self, wss_r, model, self.max_tokens)
                else:
                    return chat_response(self, r, self.prompt_tokens, model, self.max_tokens)
            else:
                raise HTTPException(status_code=r.status_code, detail="Unsupported Content-Type")
        except HTTPException as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail)

    async def get_image_download_url(self, asset_pointer):
        image_url = f"{self.base_url}/files/{asset_pointer}/download"
        headers = {
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Content-Type': 'application/json',
            'Oai-Device-Id': self.oai_device_id,
            'Oai-Language': 'en-US',
            'Origin': 'https://chat.openai.com',
            'Referer': 'https://chat.openai.com/',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': self.user_agent
        }
        if self.access_token:
            headers['Authorization'] = f'Bearer {self.access_token}'
        try:
            r = await self.s.get(image_url, headers=headers)
            if r.status_code == 200:
                download_url = r.json().get('download_url')
                return download_url
            else:
                return ""
        except HTTPException as e:
            return ""
