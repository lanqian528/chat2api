import json
import random
import types
import uuid

import websockets
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from api.files import get_image_size, get_file_extension, determine_file_use_case
from api.models import model_proxy
from chatgpt.chatFormat import api_messages_to_chat, stream_response, wss_stream_response, format_not_stream_response
from chatgpt.proofofWork import calc_proof_token, calc_config_token, get_config, get_dpl
from utils.Client import Client
from utils.Logger import logger
from utils.config import proxy_url_list, chatgpt_base_url_list, arkose_token_url_list, history_disabled


class ChatService:
    def __init__(self, access_token=None):
        # some configs need to be saved accross conversations
        self.ws = None
        self.wss_url = None
        self.wss_mode = False
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
        self.access_token = access_token
        self.chat_token = "gAAAAAB"

    async def set_dynamic_data(self, data):
        self.proxy_url = random.choice(proxy_url_list) if proxy_url_list else None
        self.host_url = random.choice(chatgpt_base_url_list)
        self.arkose_token_url = random.choice(arkose_token_url_list) if arkose_token_url_list else None
        self.s = Client(proxy=self.proxy_url)
        if self.access_token:
            self.base_url = self.host_url + "/backend-api"
        else:
            self.base_url = self.host_url + "/backend-anon"
        self.oai_device_id = str(uuid.uuid4())
        self.persona = None
        self.arkose_token = None
        self.proof_token = None

        self.parent_message_id = data.get('parent_message_id')
        self.conversation_id = data.get('conversation_id')
        self.history_disabled = data.get('history_disabled', history_disabled)

        self.data = data
        self.origin_model = self.data.get("model", "gpt-3.5-turbo-0125")
        self.target_model = model_proxy.get(self.origin_model, self.origin_model)
        self.api_messages = self.data.get("messages", [])
        self.prompt_tokens = 0
        self.max_tokens = self.data.get("max_tokens", 2147483647)

        self.headers = None
        self.chat_request = None

        self.s.session.cookies.set("__Secure-next-auth.callback-url", "https%3A%2F%2Fchatgpt.com;", secure=True)

    async def get_wss_url(self):
        url = f'{self.base_url}/register-websocket'
        headers = {
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Content-Type': 'application/json',
            'Oai-Device-Id': self.oai_device_id,
            'Oai-Language': 'en-US',
            'Origin': 'https://chatgpt.com',
            'Priority': 'u=1, i',
            'Referer': 'https://chatgpt.com/',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': self.user_agent
        }
        if self.access_token:
            headers['Authorization'] = f'Bearer {self.access_token}'
            pass
        body = ''
        logger.debug(f"url:{url}\nheaders:{headers}\ndata:{body}")
        r = await self.s.post(url, headers=headers, data=body)
        if r.status_code == 200:
            resp = r.json()
            logger.info(f'register-websocket response:{resp}')
            wss_url = resp.get('wss_url')
            return wss_url
        return None

    async def get_chat_requirements(self):
        url = f'{self.base_url}/sentinel/chat-requirements'
        headers = {
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Content-Type': 'application/json',
            'Oai-Device-Id': self.oai_device_id,
            'Oai-Language': 'en-US',
            'Origin': self.host_url,
            'Referer': f'{self.host_url}/',
            'User-Agent': self.user_agent
        }
        if self.access_token:
            headers['Authorization'] = f'Bearer {self.access_token}'
        try:
            await get_dpl(self)
            config = get_config(self.user_agent)
            data = {'p': calc_config_token(config)}
            r = await self.s.post(url, headers=headers, json=data)
            if r.status_code == 200:
                resp = r.json()
                self.persona = resp.get("persona")
                if "gpt-4" in self.origin_model and self.persona != "chatgpt-paid":
                    raise HTTPException(status_code=404, detail={
                        "message": f"The model `{self.origin_model}` does not exist or you do not have access to it.",
                        "type": "invalid_request_error",
                        "param": None,
                        "code": "model_not_found"
                    })
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
                        logger.info(f"arkose_token: {r2esp}")
                        self.arkose_token = r2esp.get('token')
                    except Exception:
                        raise HTTPException(status_code=403, detail="Failed to get Arkose token")
                    finally:
                        await arkose_client.close()

                proofofwork_required = proofofwork.get('required')
                if proofofwork_required:
                    proofofwork_seed = proofofwork.get("seed")
                    proofofwork_diff = proofofwork.get("difficulty")
                    self.proof_token = await run_in_threadpool(calc_proof_token, proofofwork_seed, proofofwork_diff, config)

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
                    detail = r.text
                if r.status_code == 403:
                    raise HTTPException(status_code=r.status_code, detail="cf-please-wait")
                elif r.status_code == 429:
                    if "cf-please-wait" in detail:
                        raise HTTPException(status_code=r.status_code, detail="cf-please-wait")
                    else:
                        raise HTTPException(status_code=r.status_code, detail="rate-limit")
                raise HTTPException(status_code=r.status_code, detail=detail)
        except HTTPException as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    async def prepare_send_conversation(self):
        chat_messages, self.prompt_tokens = await api_messages_to_chat(self, self.api_messages)
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
            'Origin': self.host_url,
            'Referer': f'{self.host_url}/',
            'User-Agent': self.user_agent
        }
        if self.access_token:
            self.headers['Authorization'] = f'Bearer {self.access_token}'
        if "gizmo" in self.origin_model:
            model = "gpt-4"
            gizmo_id = self.data.get("model").split("gpt-4-gizmo-")[-1]
            conversation_mode = {"kind": "gizmo_interaction", "gizmo_id": gizmo_id}
        elif "gpt-4-mobile" in self.origin_model:
            model = "gpt-4-mobile"
            conversation_mode = {"kind": "primary_assistant"}
        elif "gpt-4" in self.origin_model:
            model = "gpt-4"
            conversation_mode = {"kind": "primary_assistant"}
        else:
            model = "text-davinci-002-render-sha"
            conversation_mode = {"kind": "primary_assistant"}
        logger.info(f"Model mapping: {self.origin_model} -> {model}")
        self.chat_request = {
            "action": "next",
            "messages": chat_messages,
            "parent_message_id": self.parent_message_id if self.parent_message_id else f"{uuid.uuid4()}",
            "model": model,
            "timezone_offset_min": -480,
            "suggestions": [],
            "history_and_training_disabled": self.history_disabled,
            "conversation_mode": conversation_mode,
            "force_paragen": False,
            "force_paragen_model_slug": "",
            "force_nulligen": False,
            "force_rate_limit": False,
            "websocket_request_id": f"{uuid.uuid4()}"
        }
        if self.conversation_id:
            self.chat_request['conversation_id'] = self.conversation_id
        return self.chat_request

    async def send_conversation(self):
        try:
            subprotocols = ["json.reliable.webpubsub.azure.v1"]
            wss_r = None
            try:
                if self.wss_mode:
                    if not self.wss_url:
                        self.wss_url = await self.get_wss_url() # first wss_url
                    # websocket connection has to be established before posting conversation to avoid message loss.
                    if self.wss_url:
                        self.ws = await websockets.connect(self.wss_url, ping_interval=None, subprotocols=subprotocols)
                        wss_r = wss_stream_response(self.ws)
            except websockets.exceptions.InvalidStatusCode as e:
                raise HTTPException(status_code=e.status_code, detail=str(e))
            url = f'{self.base_url}/conversation'
            stream = self.data.get("stream", False)
            r = await self.s.post_stream(url, headers=self.headers, json=self.chat_request, timeout=600, stream=True)
            if r.status_code != 200:
                if r.status_code == 403:
                    detail = "cf-please-wait"
                else:
                    rtext = await r.atext()
                    detail = json.loads(rtext).get("detail", rtext)
                raise HTTPException(status_code=r.status_code, detail=detail)

            content_type = r.headers.get("Content-Type", "")
            if "text/event-stream" in content_type and stream:
                self.wss_mode = False
                return stream_response(self, r.aiter_lines(), self.target_model, self.max_tokens)
            elif "text/event-stream" in content_type and not stream:
                self.wss_mode = False
                return await format_not_stream_response(stream_response(self, r.aiter_lines(), self.target_model, self.max_tokens), self.prompt_tokens, self.max_tokens, self.target_model)
            elif "application/json" in content_type:
                self.wss_mode = True
                rtext = await r.atext()
                resp = json.loads(rtext)
                self.wss_url = resp.get('wss_url') # used for next wss_url
                logger.info(f"next wss_url: {self.wss_url}")
                if wss_r:
                    try:
                        if stream and isinstance(wss_r, types.AsyncGeneratorType):
                            return stream_response(self, wss_r, self.target_model, self.max_tokens)
                        else:
                            return await format_not_stream_response(stream_response(self, wss_r, self.target_model, self.max_tokens), self.prompt_tokens, self.max_tokens, self.target_model)
                    finally:
                        if not isinstance(wss_r, types.AsyncGeneratorType):
                            await self.ws.close()
                else: # switching to websocket mode
                    raise HTTPException(status_code=500, detail="switching to websocket mode...")
            else:
                raise HTTPException(status_code=r.status_code, detail="Unsupported Content-Type")
        except HTTPException as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    async def get_download_url(self, file_id):
        url = f"{self.base_url}/files/{file_id}/download"
        headers = {
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Content-Type': 'application/json',
            'Oai-Device-Id': self.oai_device_id,
            'Oai-Language': 'en-US',
            'Origin': self.host_url,
            'Referer': f'{self.host_url}/',
            'User-Agent': self.user_agent
        }
        if self.access_token:
            headers['Authorization'] = f'Bearer {self.access_token}'
        try:
            r = await self.s.get(url, headers=headers)
            if r.status_code == 200:
                download_url = r.json().get('download_url')
                return download_url
            else:
                return ""
        except HTTPException:
            return ""

    async def get_download_url_from_upload(self, file_id):
        url = f"{self.base_url}/files/{file_id}/uploaded"
        headers = {
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Content-Type': 'application/json',
            'Oai-Device-Id': self.oai_device_id,
            'Oai-Language': 'en-US',
            'Origin': self.host_url,
            'Referer': f'{self.host_url}/',
            'User-Agent': self.user_agent
        }
        if self.access_token:
            headers['Authorization'] = f'Bearer {self.access_token}'
        try:
            r = await self.s.post(url, headers=headers, json={})
            if r.status_code == 200:
                download_url = r.json().get('download_url')
                return download_url
            else:
                return ""
        except HTTPException:
            return ""

    async def get_upload_url(self, file_name, file_size, use_case="multimodal"):
        url = f'{self.base_url}/files'
        headers = {
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Content-Type': 'application/json',
            'Oai-Device-Id': self.oai_device_id,
            'Oai-Language': 'en-US',
            'Origin': self.host_url,
            'Referer': f'{self.host_url}/',
            'User-Agent': self.user_agent
        }
        if self.access_token:
            headers['Authorization'] = f'Bearer {self.access_token}'
        try:
            r = await self.s.post(url, headers=headers, json={
                "file_name": file_name,
                "file_size": file_size,
                "timezone_offset_min": -480,
                "use_case": use_case
            })
            if r.status_code == 200:
                res = r.json()
                file_id = res.get('file_id')
                upload_url = res.get('upload_url')
                logger.info(f"file_id: {file_id}, upload_url: {upload_url}")
                return file_id, upload_url
            else:
                return "", ""
        except HTTPException:
            return "", ""

    async def upload(self, upload_url, file_content, mime_type):
        headers = {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'en-US,en;q=0.9',
            'Content-Type': mime_type,
            'Origin': self.host_url,
            'Referer': f'{self.host_url}/',
            'User-Agent': self.user_agent,
            'X-Ms-Blob-Type': 'BlockBlob',
            'X-Ms-Version': '2020-04-08'
        }
        try:
            r = await self.s.put(upload_url, headers=headers, data=file_content)
            if r.status_code == 201:
                return True
            return False
        except Exception:
            return False

    async def close_client(self):
        await self.s.close()
        if self.ws:
            await self.ws.close()

    async def upload_file(self, file_content, mime_type):
        width, height = None, None
        if mime_type.startswith("image/"):
            try:
                width, height = await get_image_size(file_content)
            except Exception as e:
                logger.error(f"Error image mime_type, change to text/plain: {e}")
                mime_type = 'text/plain'
        file_size = len(file_content)
        file_extension = await get_file_extension(mime_type)
        file_name = f"{uuid.uuid4()}{file_extension}"
        use_case = await determine_file_use_case(mime_type)
        if use_case == "ace_upload":
            mime_type = ''
            logger.error(f"Error file mime_type, change to None")

        file_id, upload_url = await self.get_upload_url(file_name, file_size, use_case)
        if file_id and upload_url:
            if await self.upload(upload_url, file_content, mime_type):
                download_url = await self.get_download_url_from_upload(file_id)
                if download_url:
                    file_meta = {
                        "file_id": file_id,
                        "file_name": file_name,
                        "size_bytes": file_size,
                        "mime_type": mime_type,
                        "width": width,
                        "height": height
                    }
                    logger.info(f"File_meta: {file_meta}")
                    return file_meta
                else:
                    logger.error("Failed to get download url")
            else:
                logger.error("Failed to upload file")
        else:
            logger.error("Failed to get upload url")
