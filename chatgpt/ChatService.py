import asyncio
import json
import random
import uuid

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from api.files import get_image_size, get_file_extension, determine_file_use_case
from api.models import model_proxy
from chatgpt.authorization import get_req_token, verify_token
from chatgpt.chatFormat import api_messages_to_chat, stream_response, format_not_stream_response, head_process_response
from chatgpt.chatLimit import check_is_limit, handle_request_limit
from chatgpt.proofofWork import get_config, get_dpl, get_answer_token, get_requirements_token
from chatgpt.turnstile import process_turnstile
from utils.Client import Client
from utils.Logger import logger
from utils.config import proxy_url_list, chatgpt_base_url_list, ark0se_token_url_list, history_disabled, pow_difficulty, \
    conversation_only, enable_limit, upload_by_url, check_model, auth_key, user_agents_list


class ChatService:
    def __init__(self, origin_token=None):
        self.user_agent = random.choice(user_agents_list) if user_agents_list else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
        self.req_token = get_req_token(origin_token)
        self.chat_token = "gAAAAAB"
        self.s = None
        self.ws = None

    async def set_dynamic_data(self, data):
        if self.req_token:
            logger.info(f"Request token: {self.req_token}")
            req_len = len(self.req_token.split(","))
            if req_len == 1:
                self.access_token = await verify_token(self.req_token)
                self.account_id = None
            else:
                self.access_token = await verify_token(self.req_token.split(",")[0])
                self.account_id = self.req_token.split(",")[1]
        else:
            logger.info("Request token is empty, use no-auth 3.5")
            self.access_token = None
            self.account_id = None

        self.data = data
        await self.set_model()
        if enable_limit and self.req_token:
            limit_response = await handle_request_limit(self.req_token, self.req_model)
            if limit_response:
                raise HTTPException(status_code=429, detail=limit_response)

        self.account_id = self.data.get('Chatgpt-Account-Id', self.account_id)
        self.parent_message_id = self.data.get('parent_message_id')
        self.conversation_id = self.data.get('conversation_id')
        self.history_disabled = self.data.get('history_disabled', history_disabled)

        self.api_messages = self.data.get("messages", [])
        self.prompt_tokens = 0
        self.max_tokens = self.data.get("max_tokens", 2147483647)
        if not isinstance(self.max_tokens, int):
            self.max_tokens = 2147483647

        self.proxy_url = random.choice(proxy_url_list) if proxy_url_list else None
        self.host_url = random.choice(chatgpt_base_url_list) if chatgpt_base_url_list else "https://chatgpt.com"
        self.ark0se_token_url = random.choice(ark0se_token_url_list) if ark0se_token_url_list else None

        self.s = Client(proxy=self.proxy_url)

        self.oai_device_id = str(uuid.uuid4())
        self.persona = None
        self.ark0se_token = None
        self.proof_token = None
        self.turnstile_token = None

        self.chat_headers = None
        self.chat_request = None

        self.base_headers = {
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'en-US,en;q=0.9',
            'Content-Type': 'application/json',
            'Oai-Device-Id': self.oai_device_id,
            'Oai-Language': 'en-US',
            'Origin': self.host_url,
            'Priority': 'u=1, i',
            'Referer': f'{self.host_url}/',
            'Sec-Ch-Ua': '"Chromium";v="124", "Microsoft Edge";v="124", "Not-A.Brand";v="99"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': self.user_agent
        }
        if self.access_token:
            self.base_url = self.host_url + "/backend-api"
            self.base_headers['Authorization'] = f'Bearer {self.access_token}'
            if self.account_id:
                self.base_headers['Chatgpt-Account-Id'] = self.account_id
        else:
            self.base_url = self.host_url + "/backend-anon"

        if auth_key:
            self.base_headers['authkey'] = auth_key

        await get_dpl(self)
        self.s.session.cookies.set("__Secure-next-auth.callback-url", "https%3A%2F%2Fchatgpt.com;",
                                   domain=self.host_url.split("://")[1], secure=True)

    async def set_model(self):
        self.origin_model = self.data.get("model", "gpt-3.5-turbo-0125")
        self.resp_model = model_proxy.get(self.origin_model, self.origin_model)
        if "o1-preview" in self.origin_model:
            self.req_model = "o1-preview"
        elif "o1-mini" in self.origin_model:
            self.req_model = "o1-mini"
        elif "o1" in self.origin_model:
            self.req_model = "o1"
        elif "gpt-4o-mini" in self.origin_model:
            self.req_model = "gpt-4o-mini"
        elif "gpt-4o" in self.origin_model:
            self.req_model = "gpt-4o"
        elif "gpt-4-mobile" in self.origin_model:
            self.req_model = "gpt-4-mobile"
        elif "gpt-4-gizmo" in self.origin_model:
            self.req_model = "gpt-4o"
        elif "gpt-4" in self.origin_model:
            self.req_model = "gpt-4"
        elif "gpt-3.5" in self.origin_model:
            self.req_model = "text-davinci-002-render-sha"
        elif "auto" in self.origin_model:
            self.req_model = "auto"
        else:
            self.req_model = "auto"

    async def get_chat_requirements(self):
        if conversation_only:
            return None
        url = f'{self.base_url}/sentinel/chat-requirements'
        headers = self.base_headers.copy()
        try:
            config = get_config(self.user_agent)
            p = get_requirements_token(config)
            data = {'p': p}
            r = await self.s.post(url, headers=headers, json=data, timeout=5)
            if r.status_code == 200:
                resp = r.json()

                if check_model:
                    r = await self.s.get(f'{self.base_url}/models', headers=headers, timeout=5)
                    if r.status_code == 200:
                        models = r.json().get('models')
                        if not any(self.req_model in model.get("slug", "") for model in models):
                            logger.error(f"Model {self.req_model} not support.")
                            raise HTTPException(status_code=404, detail={
                                "message": f"The model `{self.origin_model}` does not exist or you do not have access to it.",
                                "type": "invalid_request_error",
                                "param": None,
                                "code": "model_not_found"
                            })
                    else:
                        raise HTTPException(status_code=404, detail="Failed to get models")
                else:
                    self.persona = resp.get("persona")
                    if self.persona != "chatgpt-paid":
                        if self.req_model == "gpt-4":
                            logger.error(f"Model {self.resp_model} not support for {self.persona}")
                            raise HTTPException(status_code=404, detail={
                                "message": f"The model `{self.origin_model}` does not exist or you do not have access to it.",
                                "type": "invalid_request_error",
                                "param": None,
                                "code": "model_not_found"
                            })

                turnstile = resp.get('turnstile', {})
                turnstile_required = turnstile.get('required')
                if turnstile_required:
                    turnstile_dx = turnstile.get("dx")
                    try:
                        self.turnstile_token = process_turnstile(turnstile_dx, p)
                    except Exception as e:
                        logger.info(f"Turnstile ignored: {e}")
                    # raise HTTPException(status_code=403, detail="Turnstile required")

                ark0se = resp.get('ark' + 'ose', {})
                ark0se_required = ark0se.get('required')
                if ark0se_required:
                    if self.persona == "chatgpt-freeaccount":
                        ark0se_method = "chat35"
                    else:
                        ark0se_method = "chat4"
                    if not self.ark0se_token_url:
                        raise HTTPException(status_code=403, detail="Ark0se service required")
                    ark0se_dx = ark0se.get("dx")
                    ark0se_client = Client()
                    try:
                        r2 = await ark0se_client.post(
                            url=self.ark0se_token_url,
                            json={"blob": ark0se_dx, "method": ark0se_method},
                            timeout=15
                        )
                        r2esp = r2.json()
                        logger.info(f"ark0se_token: {r2esp}")
                        if r2esp.get('solved', True):
                            self.ark0se_token = r2esp.get('token')
                        else:
                            raise HTTPException(status_code=403, detail="Failed to get Ark0se token")
                    except Exception:
                        raise HTTPException(status_code=403, detail="Failed to get Ark0se token")
                    finally:
                        await ark0se_client.close()

                proofofwork = resp.get('proofofwork', {})
                proofofwork_required = proofofwork.get('required')
                if proofofwork_required:
                    proofofwork_diff = proofofwork.get("difficulty")
                    if proofofwork_diff <= pow_difficulty:
                        raise HTTPException(status_code=403,
                                            detail=f"Proof of work difficulty too high: {proofofwork_diff}")
                    proofofwork_seed = proofofwork.get("seed")
                    self.proof_token, solved = await run_in_threadpool(get_answer_token, proofofwork_seed,
                                                                       proofofwork_diff, config)
                    if not solved:
                        raise HTTPException(status_code=403, detail="Failed to solve proof of work")

                self.chat_token = resp.get('token')
                if not self.chat_token:
                    raise HTTPException(status_code=403, detail=f"Failed to get chat token: {r.text}")
                return self.chat_token
            else:
                if "application/json" == r.headers.get("Content-Type", ""):
                    detail = r.json().get("detail", r.json())
                else:
                    detail = r.text
                if "cf-please-wait" in detail:
                    raise HTTPException(status_code=r.status_code, detail="cf-please-wait")
                if r.status_code == 429:
                    raise HTTPException(status_code=r.status_code, detail="rate-limit")
                raise HTTPException(status_code=r.status_code, detail=detail)
        except HTTPException as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    async def prepare_send_conversation(self):
        try:
            chat_messages, self.prompt_tokens = await api_messages_to_chat(self, self.api_messages, upload_by_url)
        except Exception as e:
            logger.error(f"Failed to format messages: {str(e)}")
            raise HTTPException(status_code=400, detail="Failed to format messages.")
        self.chat_headers = self.base_headers.copy()
        self.chat_headers.update({
            'Accept': 'text/event-stream',
            'Openai-Sentinel-Chat-Requirements-Token': self.chat_token,
            'Openai-Sentinel-Proof-Token': self.proof_token,
        })
        if self.ark0se_token:
            self.chat_headers['Openai-Sentinel-Ark' + 'ose-Token'] = self.ark0se_token

        if self.turnstile_token:
            self.chat_headers['Openai-Sentinel-Turnstile-Token'] = self.turnstile_token

        if conversation_only:
            self.chat_headers.pop('Openai-Sentinel-Chat-Requirements-Token', None)
            self.chat_headers.pop('Openai-Sentinel-Proof-Token', None)
            self.chat_headers.pop('Openai-Sentinel-Ark' + 'ose-Token', None)
            self.chat_headers.pop('Openai-Sentinel-Turnstile-Token', None)

        if "gpt-4-gizmo" in self.origin_model:
            gizmo_id = self.origin_model.split("gpt-4-gizmo-")[-1]
            conversation_mode = {"kind": "gizmo_interaction", "gizmo_id": gizmo_id}
        else:
            conversation_mode = {"kind": "primary_assistant"}

        logger.info(f"Model mapping: {self.origin_model} -> {self.req_model}")
        self.chat_request = {
            "action": "next",
            "conversation_mode": conversation_mode,
            "force_nulligen": False,
            "force_paragen": False,
            "force_paragen_model_slug": "",
            "force_rate_limit": False,
            "force_use_sse": True,
            "history_and_training_disabled": self.history_disabled,
            "messages": chat_messages,
            "model": self.req_model,
            "parent_message_id": self.parent_message_id if self.parent_message_id else f"{uuid.uuid4()}",
            "reset_rate_limits": False,
            "suggestions": [],
            "timezone_offset_min": -480,
            "variant_purpose": "comparison_implicit",
            "websocket_request_id": f"{uuid.uuid4()}"
        }
        if self.conversation_id:
            self.chat_request['conversation_id'] = self.conversation_id
        return self.chat_request

    async def send_conversation(self):
        try:
            url = f'{self.base_url}/conversation'
            stream = self.data.get("stream", False)
            r = await self.s.post_stream(url, headers=self.chat_headers, json=self.chat_request, timeout=10,
                                         stream=True)
            if r.status_code != 200:
                rtext = await r.atext()
                if "application/json" == r.headers.get("Content-Type", ""):
                    detail = json.loads(rtext).get("detail", json.loads(rtext))
                    if r.status_code == 429:
                        check_is_limit(detail, token=self.req_token, model=self.req_model)
                else:
                    if "cf-please-wait" in rtext:
                        # logger.error(f"Failed to send conversation: cf-please-wait")
                        raise HTTPException(status_code=r.status_code, detail="cf-please-wait")
                    if r.status_code == 429:
                        # logger.error(f"Failed to send conversation: rate-limit")
                        raise HTTPException(status_code=r.status_code, detail="rate-limit")
                    detail = r.text[:100]
                # logger.error(f"Failed to send conversation: {detail}")
                raise HTTPException(status_code=r.status_code, detail=detail)

            content_type = r.headers.get("Content-Type", "")
            if "text/event-stream" in content_type:
                res, start = await head_process_response(r.aiter_lines())
                if not start:
                    raise HTTPException(status_code=403, detail="Our systems have detected unusual activity coming from your system. Please try again later.")
                if stream:
                    return stream_response(self, res, self.resp_model, self.max_tokens)
                else:
                    return await format_not_stream_response(
                        stream_response(self, res, self.resp_model, self.max_tokens), self.prompt_tokens,
                        self.max_tokens, self.resp_model)
            elif "application/json" in content_type:
                rtext = await r.atext()
                resp = json.loads(rtext)
                raise HTTPException(status_code=r.status_code, detail=resp)
            else:
                rtext = await r.atext()
                raise HTTPException(status_code=r.status_code, detail=rtext)
        except HTTPException as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    async def get_download_url(self, file_id):
        url = f"{self.base_url}/files/{file_id}/download"
        headers = self.base_headers.copy()
        try:
            r = await self.s.get(url, headers=headers, timeout=5)
            if r.status_code == 200:
                download_url = r.json().get('download_url')
                return download_url
            else:
                return ""
        except HTTPException:
            return ""

    async def get_download_url_from_upload(self, file_id):
        url = f"{self.base_url}/files/{file_id}/uploaded"
        headers = self.base_headers.copy()
        try:
            r = await self.s.post(url, headers=headers, json={}, timeout=5)
            if r.status_code == 200:
                download_url = r.json().get('download_url')
                return download_url
            else:
                return ""
        except HTTPException:
            return ""

    async def get_upload_url(self, file_name, file_size, use_case="multimodal"):
        url = f'{self.base_url}/files'
        headers = self.base_headers.copy()
        try:
            r = await self.s.post(url, headers=headers, json={
                "file_name": file_name,
                "file_size": file_size,
                "timezone_offset_min": -480,
                "use_case": use_case
            }, timeout=5)
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
        headers = self.base_headers.copy()
        headers.update({
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': mime_type,
            'X-Ms-Blob-Type': 'BlockBlob',
            'X-Ms-Version': '2020-04-08'
        })
        headers.pop('Authorization', None)
        try:
            r = await self.s.put(upload_url, headers=headers, data=file_content)
            if r.status_code == 201:
                return True
            return False
        except Exception:
            return False

    async def upload_file(self, file_content, mime_type):
        if not file_content or not mime_type:
            return None

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
                        "height": height,
                        "use_case": use_case
                    }
                    logger.info(f"File_meta: {file_meta}")
                    return file_meta
                else:
                    logger.error("Failed to get download url")
            else:
                logger.error("Failed to upload file")
        else:
            logger.error("Failed to get upload url")

    async def check_upload(self, file_id):
        url = f'{self.base_url}/files/{file_id}'
        headers = self.base_headers.copy()
        try:
            for i in range(30):
                r = await self.s.get(url, headers=headers, timeout=5)
                if r.status_code == 200:
                    res = r.json()
                    retrieval_index_status = res.get('retrieval_index_status', '')
                    if retrieval_index_status == "success":
                        break
                await asyncio.sleep(1)
            return True
        except HTTPException:
            return False

    async def get_response_file_url(self, conversation_id, message_id, sandbox_path):
        try:
            url = f"{self.base_url}/conversation/{conversation_id}/interpreter/download"
            params = {
                "message_id": message_id,
                "sandbox_path": sandbox_path
            }
            headers = self.base_headers.copy()
            r = await self.s.get(url, headers=headers, params=params, timeout=10)
            if r.status_code == 200:
                return r.json().get("download_url")
            else:
                return None
        except Exception:
            logger.info("Failed to get response file url")
            return None

    async def close_client(self):
        if self.s:
            await self.s.close()
        if self.ws:
            await self.ws.close()
            del self.ws
