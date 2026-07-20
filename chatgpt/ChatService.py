import hashlib
import json
import random
import uuid

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from chatgpt.authorization import get_req_token
from chatgpt.chatFormat import api_messages_to_chat, stream_response, format_not_stream_response, head_process_response
from chatgpt.chatLimit import check_is_limit, handle_request_limit
from chatgpt.fp import get_fp
from chatgpt.proofofWork import get_config, get_dpl, get_answer_token, get_requirements_token
from chatgpt.services import AuthMixin, FileMixin, ModelMixin
from chatgpt.services._helpers import _sanitize_headers, _stringify_header_value

from utils.Client import Client
from utils.Logger import logger
from utils import antiban
from utils.configs import (
    chatgpt_base_url_list,
    ark0se_token_url_list,
    sentinel_proxy_url_list,
    history_disabled,
    pow_difficulty,
    conversation_only,
    enable_limit,
    upload_by_url,
    auth_key,
    turnstile_solver_url,
    oai_language,
    accept_language,
    chat_requirements_timeout,
    chat_request_timeout,
    client_timezone,
    client_timezone_offset_min,
    enable_antiban,
    oai_client_version,
    oai_client_build_number,
)


class ChatService(AuthMixin, ModelMixin, FileMixin):
    def __init__(self, origin_token=None):
        # self.user_agent = random.choice(user_agents_list) if user_agents_list else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
        self.req_token = get_req_token(origin_token)
        self.chat_token = "gAAAAAB"
        self.s = None
        self.ss = None
        self.ws = None
        self.dynamic_model = False
        self.antiban_ctx = None
        # 深度研究相关：system_hints 与请求体透传 / 模型名后缀双模式触发
        self.system_hints = []
        # Session sticky: 由 api 层 inject 后挂载，stream_response 嗅探时用于回写映射
        self.librechat_conv_id = None

    async def initialize_request_context(self):
        # Antiban: 在读取 fp 之前获取上下文（bucket/geo/冷却/熔断）
        self.antiban_ctx = await antiban.acquire_context(self.req_token)

        self.fp = get_fp(self.req_token).copy()
        self.proxy_url = self.fp.pop("proxy_url", None)
        self.impersonate = self.fp.pop("impersonate", "safari15_3")
        self.user_agent = self.fp.get("user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0")

        # Antiban 强制粘性 IP：以桶内 proxy 覆盖 fp 中的 proxy_url（若已分配）
        if self.antiban_ctx and self.antiban_ctx.enabled and self.antiban_ctx.proxy_url:
            if self.proxy_url != self.antiban_ctx.proxy_url:
                logger.info(
                    f"[antiban] proxy overridden by bucket: "
                    f"{self.proxy_url} -> {self.antiban_ctx.proxy_url}"
                )
            self.proxy_url = self.antiban_ctx.proxy_url

        logger.info(f"Request token: {self.req_token}")
        logger.info(f"Request proxy: {self.proxy_url}")
        logger.info(f"Request UA: {self.user_agent}")
        logger.info(f"Request impersonate: {self.impersonate}")

        self.host_url = random.choice(chatgpt_base_url_list) if chatgpt_base_url_list else "https://chatgpt.com"
        self.ark0se_token_url = random.choice(ark0se_token_url_list) if ark0se_token_url_list else None

        session_source = self.req_token or "no-auth"
        session_id = hashlib.md5(session_source.encode()).hexdigest()
        proxy_url = self.proxy_url.replace("{}", session_id) if self.proxy_url else None
        self.s = Client(proxy=proxy_url, impersonate=self.impersonate)
        if sentinel_proxy_url_list:
            sentinel_proxy_url = (random.choice(sentinel_proxy_url_list)).replace("{}", session_id) if sentinel_proxy_url_list else None
            self.ss = Client(proxy=sentinel_proxy_url, impersonate=self.impersonate)
        else:
            self.ss = self.s

        self.persona = None
        self.ark0se_token = None
        self.proof_token = None
        self.turnstile_token = None

        self.chat_headers = None
        self.chat_request = None

        self.base_headers = {
            'accept': '*/*',
            'accept-encoding': 'gzip, deflate, br, zstd',
            'accept-language': accept_language,
            'content-type': 'application/json',
            'oai-language': oai_language,
            'origin': self.host_url,
            'priority': 'u=1, i',
            'referer': f'{self.host_url}/',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin'
        }
        # 反降智关键头：让请求看起来像真实 ChatGPT 前端发出
        if oai_client_version:
            self.base_headers['oai-client-version'] = oai_client_version
        if oai_client_build_number:
            self.base_headers['oai-client-build-number'] = str(oai_client_build_number)
        # oai-session-id：与 oai-device-id 类似，token 级稳定（fp.py 在生成 fp 时填入）
        session_id_header = self.fp.get("oai-session-id")
        if session_id_header:
            self.base_headers['oai-session-id'] = session_id_header
        # T1: 注入用户偏好相关 CH 头（Chromium 真实浏览器在 same-origin 请求中默认携带）
        _pref_color = self.fp.get("color_scheme")
        if _pref_color in ("light", "dark"):
            self.base_headers['sec-ch-prefers-color-scheme'] = _pref_color
        _pref_motion = self.fp.get("prefers_reduced_motion")
        if _pref_motion in ("no-preference", "reduce"):
            self.base_headers['sec-ch-prefers-reduced-motion'] = _pref_motion
        # 过滤掉 fp 中的非 HTTP-header 内部指纹字段（screen/viewport 等仅供 PoW 与 contextual_info 使用）
        for _internal_key in (
            "screen", "hardware_concurrency", "device_memory", "pixel_ratio", "viewport",
            # 扩展指纹字段：仅供 client_contextual_info / 未来 sentinel 字段使用，绝不能进 HTTP 头
            "nav_platform", "languages", "max_touch_points", "webgl",
            "color_scheme", "prefers_reduced_motion", "color_gamut",
            "connection", "audio",
            # T2/T3/T5/M1/M2 等纯指纹字段
            "canvas_hash", "font_list_hash", "font_list_count", "audio_fp_hash",
            "timezone", "intl_locale", "user_pace", "virtual_page_load_ms",
            # D2/D3 深耕字段
            "webgpu", "webrtc",
        ):
            self.fp.pop(_internal_key, None)
        self.base_headers.update(_sanitize_headers(self.fp))

        if self.access_token:
            self.base_url = self.host_url + "/backend-api"
            self.base_headers['authorization'] = f'Bearer {self.access_token}'
            if self.account_id:
                self.base_headers['chatgpt-account-id'] = self.account_id
        else:
            self.base_url = self.host_url + "/backend-anon"

        if auth_key:
            self.base_headers['authkey'] = auth_key

        # Antiban: 用 geo 结果覆盖 accept-language / oai-language
        if self.antiban_ctx and self.antiban_ctx.enabled and self.antiban_ctx.header_overrides:
            for k, v in self.antiban_ctx.header_overrides.items():
                if k.startswith("_") or not v:
                    continue
                normalized = _stringify_header_value(v)
                if normalized is not None:
                    self.base_headers[k] = normalized
            logger.info(
                f"[antiban] headers overridden by geo: "
                f"accept-language={self.base_headers.get('accept-language')} "
                f"oai-language={self.base_headers.get('oai-language')}"
            )

    async def set_dynamic_data(self, data):
        await self.resolve_auth_context()

        self.data = data
        # 深度研究：双模式触发字段提取（必须在 set_model 之前，便于模型名识别合并）
        # 1) 显式透传 system_hints；2) 支持别名 hints；3) 支持 deep_research:bool 快捷开关
        raw_hints = self.data.get("system_hints")
        if raw_hints is None:
            raw_hints = self.data.get("hints", [])
        if not isinstance(raw_hints, list):
            raw_hints = []
        if self.data.get("deep_research") is True and "research" not in raw_hints:
            raw_hints = raw_hints + ["research"]
        self.system_hints = raw_hints

        await self.set_model()

        self.account_id = self.data.get('Chatgpt-Account-Id', self.account_id)
        self.parent_message_id = self.data.get('parent_message_id')
        self.conversation_id = self.data.get('conversation_id')
        self.history_disabled = self.data.get('history_disabled', history_disabled)

        self.api_messages = self.data.get("messages", [])
        self.prompt_tokens = 0
        self.max_tokens = self.data.get("max_tokens", 2147483647)
        if not isinstance(self.max_tokens, int):
            self.max_tokens = 2147483647

        await self.initialize_request_context()
        await get_dpl(self)
        await self.validate_model_access()

        if enable_limit and self.req_token:
            limit_response = await handle_request_limit(self.req_token, self.req_model)
            if limit_response:
                raise HTTPException(status_code=429, detail=limit_response)

    async def get_chat_requirements(self):
        if conversation_only:
            return None
        url = f'{self.base_url}/sentinel/chat-requirements'
        headers = self.base_headers.copy()
        try:
            tz_offset = self.antiban_ctx.tz_offset_min if (self.antiban_ctx and self.antiban_ctx.enabled) else None
            config = get_config(self.user_agent, self.req_token, tz_offset)
            p = get_requirements_token(config)
            data = {'p': p}
            r = await self.ss.post(url, headers=headers, json=data, timeout=chat_requirements_timeout)
            if r.status_code == 200:
                resp = r.json()

                self.persona = resp.get("persona")
                if self.persona != "chatgpt-paid":
                    if self.req_model == "gpt-4" or self.req_model == "o1-preview":
                        logger.error(f"Model {self.resp_model} not support for {self.persona}")
                        raise self.model_not_found()

                turnstile = resp.get('turnstile', {})
                turnstile_required = turnstile.get('required')
                if turnstile_required:
                    turnstile_dx = turnstile.get("dx")
                    try:
                        if turnstile_solver_url:
                            res = await self.s.post(
                                turnstile_solver_url, json={"url": "https://chatgpt.com", "p": p, "dx": turnstile_dx, "ua": self.user_agent}
                            )
                            self.turnstile_token = res.json().get("t")
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
                    ark0se_client = Client(impersonate=self.impersonate)
                    try:
                        r2 = await ark0se_client.post(
                            url=self.ark0se_token_url, json={"blob": ark0se_dx, "method": ark0se_method}, timeout=15
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
                        raise HTTPException(status_code=403, detail=f"Proof of work difficulty too high: {proofofwork_diff}")
                    proofofwork_seed = proofofwork.get("seed")
                    self.proof_token, solved = await run_in_threadpool(
                        get_answer_token, proofofwork_seed, proofofwork_diff, config
                    )
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
                # Antiban: 分级上报错误（IP 降级 / 账号冷却延长 / 黑名单）
                await antiban.report_error(self.antiban_ctx, r.status_code, detail)
                if "cf_chl_opt" in detail:
                    raise HTTPException(status_code=r.status_code, detail="cf_chl_opt")
                if r.status_code == 429:
                    raise HTTPException(status_code=r.status_code, detail="rate-limit")
                raise HTTPException(status_code=r.status_code, detail=detail)
        except HTTPException as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail)
        except Exception as e:
            # M3: transport 层失败（连接被拒/超时/DNS）→ 告知 antiban 桶降级
            try:
                await antiban.report_network_error(self.antiban_ctx, type(e).__name__)
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=str(e))

    async def prepare_send_conversation(self):
        try:
            chat_messages, self.prompt_tokens = await api_messages_to_chat(self, self.api_messages, upload_by_url)
        except Exception as e:
            logger.error(f"Failed to format messages: {str(e)}")
            raise HTTPException(status_code=400, detail="Failed to format messages.")
        self.chat_headers = self.base_headers.copy()
        self.chat_headers.update(
            {
                'accept': 'text/event-stream',
                'openai-sentinel-chat-requirements-token': self.chat_token,
                'openai-sentinel-proof-token': self.proof_token,
            }
        )
        if self.ark0se_token:
            self.chat_headers['openai-sentinel-ark' + 'ose-token'] = self.ark0se_token

        if self.turnstile_token:
            self.chat_headers['openai-sentinel-turnstile-token'] = self.turnstile_token

        if conversation_only:
            self.chat_headers.pop('openai-sentinel-chat-requirements-token', None)
            self.chat_headers.pop('openai-sentinel-proof-token', None)
            self.chat_headers.pop('openai-sentinel-ark' + 'ose-token', None)
            self.chat_headers.pop('openai-sentinel-turnstile-token', None)

        if self.gizmo_id:
            conversation_mode = {"kind": "gizmo_interaction", "gizmo_id": self.gizmo_id}
            logger.info(f"Gizmo id: {self.gizmo_id}")
        else:
            conversation_mode = {"kind": "primary_assistant"}

        # 深度研究强制 primary_assistant 模式（原生协议约束）
        if "research" in self.system_hints and self.gizmo_id:
            logger.warning("Deep research forces primary_assistant mode, ignoring gizmo_id")
            conversation_mode = {"kind": "primary_assistant"}
            self.gizmo_id = None

        logger.info(f"Model mapping: {self.origin_model} -> {self.req_model}")
        if self.system_hints:
            logger.info(f"System hints: {self.system_hints}")

        # client_contextual_info：token 级稳定（首选）；同账号多次请求保持一致，避免抖动暴露自动化
        ctx_info = None
        pace_range = None
        try:
            if enable_antiban:
                from utils.antiban import fingerprint as _fp_mod
                # H3 双保险：即使上游 acquire_context 未触发，也保证扩展字段齐全
                _fp_mod.ensure_extended(self.req_token)
                ctx_info = _fp_mod.get_contextual_info(self.req_token)
                pace_range = _fp_mod.get_user_pace_range(self.req_token)
        except Exception:
            ctx_info = None
            pace_range = None

        # M1: time_since_loaded 按 user_pace 抽样（fast/normal/slow），同账号节奏一致
        if pace_range:
            time_since_loaded = random.randint(pace_range[0], pace_range[1])
        else:
            time_since_loaded = random.randint(3000, 30000)

        if ctx_info:
            # is_dark_mode 不再硬编码 False，改为 token 级稳定的 color_scheme 派生（约 30% 用户偏好暗色）
            client_contextual_info = {
                "is_dark_mode": ctx_info.get("color_scheme") == "dark",
                "time_since_loaded": time_since_loaded,
                "page_height": ctx_info["page_height"],
                "page_width": ctx_info["page_width"],
                "pixel_ratio": ctx_info["pixel_ratio"],
                "screen_height": ctx_info["screen_height"],
                "screen_width": ctx_info["screen_width"],
            }
        else:
            # antiban 未启用：保持原行为但修正 pixel_ratio 取真实值（1.0/2.0 而非 1.5）
            client_contextual_info = {
                "is_dark_mode": False,
                "time_since_loaded": time_since_loaded,
                "page_height": random.randint(700, 1200),
                "page_width": random.randint(1200, 2000),
                "pixel_ratio": random.choice([1.0, 2.0]),
                "screen_height": random.randint(900, 1440),
                "screen_width": random.randint(1440, 2560),
            }

        self.chat_request = {
            "action": "next",
            "client_contextual_info": client_contextual_info,
            "conversation_mode": conversation_mode,
            "conversation_origin": None,
            "force_paragen": False,
            "force_paragen_model_slug": "",
            "force_rate_limit": False,
            "force_use_sse": True,
            "history_and_training_disabled": self.history_disabled,
            "messages": chat_messages,
            "model": self.req_model,
            "paragen_cot_summary_display_override": "allow",
            "paragen_stream_type_override": None,
            "parent_message_id": self.parent_message_id if self.parent_message_id else f"{uuid.uuid4()}",
            "reset_rate_limits": False,
            "suggestions": [],
            "supported_encodings": [],
            "system_hints": self.system_hints,
            "timezone": client_timezone,
            "timezone_offset_min": client_timezone_offset_min,
            "variant_purpose": "comparison_implicit",
            "websocket_request_id": f"{uuid.uuid4()}",
        }
        # Antiban: 按 IP 地域覆盖时区（与 UA / accept-language 一致）
        if self.antiban_ctx and self.antiban_ctx.enabled and self.antiban_ctx.tz_offset_min is not None:
            self.chat_request["timezone_offset_min"] = self.antiban_ctx.tz_offset_min
            if self.antiban_ctx.header_overrides.get("_timezone_name"):
                self.chat_request["timezone"] = self.antiban_ctx.header_overrides["_timezone_name"]
        if self.conversation_id:
            self.chat_request['conversation_id'] = self.conversation_id
            # 真实浏览器的 referer 是具体会话 URL（如 /c/<conv_id>），不是首页
            self.chat_headers['referer'] = f"{self.host_url}/c/{self.conversation_id}"
        return self.chat_request

    async def send_conversation(self):
        try:
            url = f'{self.base_url}/conversation'
            stream = self.data.get("stream", False)
            r = await self.s.post_stream(
                url,
                headers=self.chat_headers,
                json=self.chat_request,
                timeout=chat_request_timeout,
                stream=True,
            )
            if r.status_code != 200:
                rtext = await r.atext()
                # Session sticky: 注入的 conv_id 触发 4xx → 清理映射，让重试新建对话
                if 400 <= r.status_code < 500 and self.data.get("librechat_conversation_id") \
                        and self.conversation_id:
                    try:
                        from chatgpt import session_sticky as _ss
                        _ss.drop_mapping(self.data.get("librechat_conversation_id"))
                    except Exception:
                        pass
                if "application/json" == r.headers.get("Content-Type", ""):
                    detail = json.loads(rtext).get("detail", json.loads(rtext))
                    if r.status_code == 429:
                        check_is_limit(detail, token=self.req_token, model=self.req_model)
                else:
                    if "cf_chl_opt" in rtext:
                        # logger.error(f"Failed to send conversation: cf_chl_opt")
                        await antiban.report_error(self.antiban_ctx, r.status_code, "cf_chl_opt")
                        raise HTTPException(status_code=r.status_code, detail="cf_chl_opt")
                    if r.status_code == 429:
                        # logger.error(f"Failed to send conversation: rate-limit")
                        await antiban.report_error(self.antiban_ctx, r.status_code, "rate-limit")
                        raise HTTPException(status_code=r.status_code, detail="rate-limit")
                    detail = r.text[:100]
                # logger.error(f"Failed to send conversation: {detail}")
                await antiban.report_error(self.antiban_ctx, r.status_code, detail)
                raise HTTPException(status_code=r.status_code, detail=detail)

            # 200 OK: 立即标记账号使用（真正 success 在响应流完成后由上游调度更稳，
            # 但 200 即可代表风控校验通过，此处记录冷却足够）
            await antiban.report_success(self.antiban_ctx)

            content_type = r.headers.get("Content-Type", "")
            if "text/event-stream" in content_type:
                res, start = await head_process_response(r.aiter_lines())
                if not start:
                    raise HTTPException(
                        status_code=403,
                        detail="Our systems have detected unusual activity coming from your system. Please try again later.",
                    )
                if stream:
                    return stream_response(self, res, self.resp_model, self.max_tokens)
                else:
                    return await format_not_stream_response(
                        stream_response(self, res, self.resp_model, self.max_tokens),
                        self.prompt_tokens,
                        self.max_tokens,
                        self.resp_model,
                    )
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
            # M3: send_conversation transport 层失败也上报，三次连续将触发桶降级
            try:
                await antiban.report_network_error(self.antiban_ctx, type(e).__name__)
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=str(e))

    async def close_client(self):
        if self.s:
            await self.s.close()
            del self.s
        if self.ss:
            await self.ss.close()
            del self.ss
        if self.ws:
            await self.ws.close()
            del self.ws
