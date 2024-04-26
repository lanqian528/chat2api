import json
import random
import types
import uuid

import websockets
from fastapi import HTTPException

from api.chat_completions import num_tokens_from_messages, model_proxy
from chatgpt.chatResponse import api_messages_to_chat, stream_response, wss_stream_response, format_not_stream_response
from chatgpt.proofofwork import calc_proof_token
from utils.Client import Client
from utils.Logger import Logger
from utils.config import proxy_url_list, chatgpt_base_url_list, arkose_token_url_list, history_disabled


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

        self.parent_message_id = data.get('parent_message_id')
        self.conversation_id = data.get('conversation_id')
        self.history_disabled = data.get('history_disabled', history_disabled)

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

    def prepare_send_conversation(self):
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
        self.chat_request = {
            "action": "next",
            "messages": chat_messages,
            "parent_message_id": self.parent_message_id if self.parent_message_id else f"{uuid.uuid4()}",
            "model": model,
            "timezone_offset_min": -480,
            "suggestions": [],
            "history_and_training_disabled": self.history_disabled,
            "conversation_mode": {"kind": "primary_assistant"},
            "force_paragen": False,
            "force_paragen_model_slug": "",
            "force_nulligen": False,
            "force_rate_limit": False,
            "websocket_request_id": f"{uuid.uuid4()}",
        }
        if self.conversation_id:
            self.chat_request['conversation_id'] = self.conversation_id
        return self.chat_request

    async def send_conversation(self):
        url = f'{self.base_url}/conversation'
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
            elif "text/event-stream" in content_type and not stream:
                return await format_not_stream_response(stream_response(self, r.aiter_lines(), model, self.max_tokens), self.prompt_tokens, self.max_tokens, model)
            elif "application/json" in content_type:
                rtext = await r.atext()
                detail = json.loads(rtext).get("detail", json.loads(rtext))
                wss_url = detail.get('wss_url')
                Logger.info(f"wss_url: {wss_url}")
                subprotocols = ["json.reliable.webpubsub.azure.v1"]
                try:
                    async with websockets.connect(wss_url, ping_interval=None, subprotocols=subprotocols) as websocket:
                        wss_r = wss_stream_response(websocket)
                except websockets.exceptions.InvalidStatusCode as e:
                    Logger.error(f"Invalid status code: {str(e)}")
                    raise HTTPException(status_code=e.status_code, detail=str(e))
                if stream and isinstance(wss_r, types.AsyncGeneratorType):
                    return stream_response(self, wss_r, model, self.max_tokens)
                else:
                    return await format_not_stream_response(stream_response(self, wss_r, model, self.max_tokens), self.prompt_tokens, self.max_tokens, model)
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
