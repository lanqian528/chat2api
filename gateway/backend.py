import hashlib
import json
import random
import re
import time
import uuid

from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse, Response
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

import utils.globals as globals
from app import app
from chatgpt.authorization import verify_token
from chatgpt.fp import get_fp
from chatgpt.proofofWork import get_answer_token, get_config, get_requirements_token
from gateway.chatgpt import chatgpt_html
from gateway.reverseProxy import chatgpt_reverse_proxy, content_generator, get_real_req_token, headers_reject_list, \
    headers_accept_list
from utils.Client import Client
from utils.Logger import logger
from utils.configs import x_sign, turnstile_solver_url, chatgpt_base_url_list, no_sentinel, sentinel_proxy_url_list, \
    force_no_history

banned_paths = [
    "backend-api/accounts/logout_all",
    "backend-api/accounts/deactivate",
    "backend-api/payments",
    "backend-api/subscriptions",
    "backend-api/user_system_messages",
    "backend-api/memories",
    "backend-api/settings/clear_account_user_memory",
    "backend-api/conversations/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
    "backend-api/accounts/mfa_info",
    "backend-api/accounts/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/invites",
    "admin",
]
redirect_paths = ["auth/logout"]
chatgpt_paths = ["c/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"]


@app.get("/backend-api/accounts/check/v4-2023-04-27")
async def check_account(request: Request):
    token = request.headers.get("Authorization").replace("Bearer ", "")
    check_account_response = await chatgpt_reverse_proxy(request, "backend-api/accounts/check/v4-2023-04-27")
    if len(token) == 45 or token.startswith("eyJhbGciOi"):
        return check_account_response
    else:
        check_account_str = check_account_response.body.decode('utf-8')
        check_account_info = json.loads(check_account_str)
        for key in check_account_info.get("accounts", {}).keys():
            account_id = check_account_info["accounts"][key]["account"]["account_id"]
            globals.seed_map[token]["user_id"] = \
                check_account_info["accounts"][key]["account"]["account_user_id"].split("__")[0]
            check_account_info["accounts"][key]["account"]["account_user_id"] = f"user-chatgpt__{account_id}"
        with open(globals.SEED_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(globals.seed_map, f, indent=4)
        return check_account_info


@app.get("/backend-api/gizmos/bootstrap")
async def get_gizmos_bootstrap(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if len(token) == 45 or token.startswith("eyJhbGciOi"):
        return await chatgpt_reverse_proxy(request, "backend-api/gizmos/bootstrap")
    else:
        return {"gizmos": []}


@app.get("/backend-api/gizmos/pinned")
async def get_gizmos_pinned(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if len(token) == 45 or token.startswith("eyJhbGciOi"):
        return await chatgpt_reverse_proxy(request, "backend-api/gizmos/pinned")
    else:
        return {"items": [], "cursor": None}


@app.get("/public-api/gizmos/discovery/recent")
async def get_gizmos_discovery_recent(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if len(token) == 45 or token.startswith("eyJhbGciOi"):
        return await chatgpt_reverse_proxy(request, "public-api/gizmos/discovery/recent")
    else:
        return {
            "info": {
                "id": "recent",
                "title": "Recently Used",
            },
            "list": {
                "items": [],
                "cursor": None
            }
        }


@app.get("/backend-api/gizmos/snorlax/sidebar")
async def get_gizmos_snorlax_sidebar(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if len(token) == 45 or token.startswith:
        return await chatgpt_reverse_proxy(request, "backend-api/gizmos/snorlax/sidebar")
    else:
        return {"items": [], "cursor": None}


@app.post("/backend-api/gizmos/snorlax/upsert")
async def get_gizmos_snorlax_upsert(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if len(token) == 45 or token.startswith:
        return await chatgpt_reverse_proxy(request, "backend-api/gizmos/snorlax/upsert")
    else:
        raise HTTPException(status_code=403, detail="Forbidden")


@app.get("/backend-api/subscriptions")
async def post_subscriptions(request: Request):
    return {
        "id": str(uuid.uuid4()),
        "plan_type": "pro",
        "seats_in_use": 1,
        "seats_entitled": 1,
        "active_until": "2050-01-01T00:00:00Z",
        "billing_period": None,
        "will_renew": True,
        "non_profit_org_discount_applied": None,
        "billing_currency": "USD",
        "is_delinquent": False,
        "became_delinquent_timestamp": None,
        "grace_period_end_timestamp": None
    }


@app.api_route("/backend-api/conversations", methods=["GET", "PATCH"])
async def get_conversations(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if len(token) == 45 or token.startswith("eyJhbGciOi"):
        return await chatgpt_reverse_proxy(request, "backend-api/conversations")
    if request.method == "GET":
        limit = int(request.query_params.get("limit", 28))
        offset = int(request.query_params.get("offset", 0))
        is_archived = request.query_params.get("is_archived", None)
        items = []
        for conversation_id in globals.seed_map.get(token, {}).get("conversations", []):
            conversation = globals.conversation_map.get(conversation_id, None)
            if conversation:
                if is_archived == "true":
                    if conversation.get("is_archived", False):
                        items.append(conversation)
                else:
                    if not conversation.get("is_archived", False):
                        items.append(conversation)
        items = items[int(offset):int(offset) + int(limit)]
        conversations = {
            "items": items,
            "total": len(items),
            "limit": limit,
            "offset": offset,
            "has_missing_conversations": False
        }
        return Response(content=json.dumps(conversations, indent=4), media_type="application/json")
    else:
        raise HTTPException(status_code=403, detail="Forbidden")


@app.get("/backend-api/conversation/{conversation_id}")
async def update_conversation(request: Request, conversation_id: str):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    conversation_details_response = await chatgpt_reverse_proxy(request,
                                                                f"backend-api/conversation/{conversation_id}")
    if len(token) == 45 or token.startswith("eyJhbGciOi"):
        return conversation_details_response
    else:
        conversation_details_str = conversation_details_response.body.decode('utf-8')
        conversation_details = json.loads(conversation_details_str)
        if conversation_id in globals.seed_map[token][
            "conversations"] and conversation_id in globals.conversation_map:
            globals.conversation_map[conversation_id]["title"] = conversation_details.get("title", None)
            globals.conversation_map[conversation_id]["is_archived"] = conversation_details.get("is_archived",
                                                                                                False)
            globals.conversation_map[conversation_id]["conversation_template_id"] = conversation_details.get(
                "conversation_template_id", None)
            globals.conversation_map[conversation_id]["gizmo_id"] = conversation_details.get("gizmo_id", None)
            globals.conversation_map[conversation_id]["async_status"] = conversation_details.get("async_status",
                                                                                                 None)
            with open(globals.CONVERSATION_MAP_FILE, "w", encoding="utf-8") as f:
                json.dump(globals.conversation_map, f, indent=4)
        return conversation_details_response


@app.patch("/backend-api/conversation/{conversation_id}")
async def patch_conversation(request: Request, conversation_id: str):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    patch_response = (await chatgpt_reverse_proxy(request, f"backend-api/conversation/{conversation_id}"))
    if len(token) == 45 or token.startswith("eyJhbGciOi"):
        return patch_response
    else:
        data = await request.json()
        if conversation_id in globals.seed_map[token][
            "conversations"] and conversation_id in globals.conversation_map:
            if not data.get("is_visible", True):
                globals.conversation_map.pop(conversation_id)
                globals.seed_map[token]["conversations"].remove(conversation_id)
                with open(globals.SEED_MAP_FILE, "w", encoding="utf-8") as f:
                    json.dump(globals.seed_map, f, indent=4)
            else:
                globals.conversation_map[conversation_id].update(data)
            with open(globals.CONVERSATION_MAP_FILE, "w", encoding="utf-8") as f:
                json.dump(globals.conversation_map, f, indent=4)
        return patch_response


@app.get("/backend-api/me")
async def get_me(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if len(token) == 45 or token.startswith("eyJhbGciOi"):
        return await chatgpt_reverse_proxy(request, "backend-api/me")
    else:
        me = {
            "object": "user",
            "id": "org-chatgpt",
            "email": "chatgpt@openai.com",
            "name": "ChatGPT",
            "picture": "https://cdn.auth0.com/avatars/ai.png",
            "created": int(time.time()),
            "phone_number": None,
            "mfa_flag_enabled": False,
            "amr": [],
            "groups": [],
            "orgs": {
                "object": "list",
                "data": [
                    {
                        "object": "organization",
                        "id": "org-chatgpt",
                        "created": 1715641300,
                        "title": "Personal",
                        "name": "user-chatgpt",
                        "description": "Personal org for chatgpt@openai.com",
                        "personal": True,
                        "settings": {
                            "threads_ui_visibility": "NONE",
                            "usage_dashboard_visibility": "ANY_ROLE",
                            "disable_user_api_keys": False
                        },
                        "parent_org_id": None,
                        "is_default": True,
                        "role": "owner",
                        "is_scale_tier_authorized_purchaser": None,
                        "is_scim_managed": False,
                        "projects": {
                            "object": "list",
                            "data": []
                        },
                        "groups": [],
                        "geography": None
                    }
                ]
            },
            "has_payg_project_spend_limit": True
        }
    return Response(content=json.dumps(me, indent=4), media_type="application/json")


@app.get("/backend-api/tasks")
async def get_me(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if len(token) == 45 or token.startswith("eyJhbGciOi"):
        return await chatgpt_reverse_proxy(request, "backend-api/tasks")
    else:
        tasks = {
            "tasks": [],
            "cursor": None
        }
    return Response(content=json.dumps(tasks, indent=4), media_type="application/json")


@app.get("/backend-api/user_system_messages")
async def get_me(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if len(token) == 45 or token.startswith("eyJhbGciOi"):
        return await chatgpt_reverse_proxy(request, "backend-api/user_system_messages")
    else:
        user_system_messages = {
            "object": "user_system_message_detail",
            "enabled": True,
            "about_user_message": "",
            "about_model_message": "",
            "name_user_message": "",
            "role_user_message": "",
            "traits_model_message": "",
            "other_user_message": "",
            "disabled_tools": []
        }
    return Response(content=json.dumps(user_system_messages, indent=4), media_type="application/json")


@app.get("/backend-api/memories")
async def get_me(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if len(token) == 45 or token.startswith("eyJhbGciOi"):
        return await chatgpt_reverse_proxy(request, "backend-api/memories")
    else:
        memories = {"memories":[],"memory_max_tokens":10000,"memory_num_tokens":0}
    return Response(content=json.dumps(memories, indent=4), media_type="application/json")


# @app.get("/backend-api/system_hints")
# async def get_me(request: Request):
#     token = request.headers.get("Authorization", "").replace("Bearer ", "")
#     if len(token) == 45 or token.startswith("eyJhbGciOi"):
#         return await chatgpt_reverse_proxy(request, "backend-api/system_hints")
#     else:
#         system_hints = {
#             "system_hints": [
#                 {
#                     "system_hint": "picture_v2",
#                     "name": "创建图片",
#                     "description": "Visualize ideas and concepts",
#                     "logo": "<svg fill=\"none\" viewBox=\"0 0 22 22\" xmlns=\"http://www.w3.org/2000/svg\"><path d=\"m16.902 2.304c0.8187-0.42416 1.787-0.23298 2.4072 0.38717 0.6201 0.62015 0.8113 1.5885 0.3872 2.4071-0.7866 1.5181-1.7193 2.8479-2.8417 4.0435 1.1284 1.4032 1.9764 2.8568 2.3346 4.2247 0.4175 1.5942 0.1834 3.2014-1.1994 4.3077-1.1107 0.8885-2.3588 0.7686-3.3556 0.3569-0.9702-0.4008-1.8307-1.1176-2.4214-1.6881-0.3641-0.3517-0.3742-0.932-0.0224-1.2962 0.3517-0.3641 0.932-0.3742 1.2961-0.0225 0.532 0.5139 1.195 1.0427 1.8477 1.3123 0.6261 0.2587 1.1004 0.2339 1.5103-0.094 0.6469-0.5176 0.8677-1.2794 0.5712-2.4116-0.2612-0.9974-0.9109-2.1738-1.8885-3.4132-0.5323 0.463-1.1008 0.9058-1.7087 1.3325-0.027 0.019-0.0546 0.0363-0.0828 0.0519-0.0568 0.6667-0.2811 1.2371-0.676 1.6918-0.4495 0.5176-1.0422 0.7951-1.6087 0.9495-0.903 0.2461-1.9839 0.2303-2.7726 0.2188-0.15178-0.0022-0.29274-0.0043-0.41953-0.0043-0.50626 0-0.91666-0.4104-0.91666-0.9166 0-0.1268-0.00206-0.2678-0.00427-0.4195-0.01149-0.7887-0.02725-1.8696 0.21885-2.7726 0.15439-0.56651 0.43185-1.1593 0.94945-1.6088 0.45468-0.39487 1.0252-0.61914 1.6919-0.67597 0.0156-0.02818 0.0329-0.05583 0.0518-0.0828 0.3644-0.51911 0.7406-1.0095 1.1309-1.4731-2.6496-1.4543-5.1975-1.3354-6.519-0.01387-0.88711 0.88711-1.2375 2.2875-0.92283 3.9656 0.31366 1.6728 1.2805 3.522 2.8674 5.1089 0.93686 0.9369 1.9491 1.5911 2.7771 2.0091 0.41354 0.2088 0.77359 0.3548 1.0457 0.4465 0.2037 0.0686 0.3205 0.0939 0.3634 0.1032 0.0226 0.0049 0.0246 0.0053 0.0078 0.0053 0.5063 0 0.9167 0.4104 0.9167 0.9167s-0.4104 0.9167-0.9167 0.9166c-0.2776 0-0.635-0.0961-0.9564-0.2044-0.36088-0.1216-0.8013-0.3022-1.2867-0.5473-0.96991-0.4896-2.1496-1.2517-3.2473-2.3493-1.814-1.814-2.9828-3.9868-3.3729-6.0675-0.38915-2.0754-0.01137-4.16 1.4284-5.5998 2.2489-2.249 5.9795-1.922 9.0975-0.06649 1.2458-1.2059 2.6376-2.1982 4.2389-3.0279zm-4.749 6.3774c0.4827 0.28036 0.8856 0.68317 1.1659 1.1659 2.0754-1.5631 3.5853-3.3452 4.7496-5.5925 0.0362-0.06982 0.0317-0.17995-0.0557-0.26737-0.0874-0.08741-0.1975-0.09189-0.2674-0.05572-2.2472 1.1644-4.0293 2.6743-5.5924 4.7496zm-2.9847 4.1507c0.65462 0.0034 1.2725-0.0135 1.8007-0.1575 0.3559-0.097 0.575-0.2311 0.7066-0.3827 0.1192-0.1373 0.2413-0.3736 0.2413-0.8378 0-0.757-0.6136-1.3707-1.3706-1.3707-0.4642 0-0.70058 0.1221-0.83784 0.2413-0.1516 0.1317-0.28575 0.3507-0.38276 0.7066-0.14395 0.5283-0.16088 1.1461-0.15742 1.8008z\" fill=\"currentColor\"/></svg>",
#                     "required_features": [
#                         "image_gen_tool_enabled"
#                     ],
#                     "required_models": [],
#                     "required_conversation_modes": [],
#                     "allow_in_temporary_chat": True,
#                     "composer_bar_button_info": None,
#                     "suggested_prompt": {
#                         "theme": "#512AEB",
#                         "title": "创建图片",
#                         "subtitle": "Visualize ideas and concepts",
#                         "sort_order": 2,
#                         "badge": None
#                     },
#                     "regex_matches": [
#                         "image"
#                     ]
#                 },
#                 {
#                     "system_hint": "search",
#                     "name": "搜索",
#                     "description": "在网上查找",
#                     "logo": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\" xmlns=\"http://www.w3.org/2000/svg\" class=\"\"><path fill-rule=\"evenodd\" clip-rule=\"evenodd\" d=\"M2 12C2 6.47715 6.47715 2 12 2C17.5228 2 22 6.47715 22 12C22 17.5228 17.5228 22 12 22C6.47715 22 2 17.5228 2 12ZM11.9851 4.00291C11.9933 4.00046 11.9982 4.00006 11.9996 4C12.001 4.00006 12.0067 4.00046 12.0149 4.00291C12.0256 4.00615 12.047 4.01416 12.079 4.03356C12.2092 4.11248 12.4258 4.32444 12.675 4.77696C12.9161 5.21453 13.1479 5.8046 13.3486 6.53263C13.6852 7.75315 13.9156 9.29169 13.981 11H10.019C10.0844 9.29169 10.3148 7.75315 10.6514 6.53263C10.8521 5.8046 11.0839 5.21453 11.325 4.77696C11.5742 4.32444 11.7908 4.11248 11.921 4.03356C11.953 4.01416 11.9744 4.00615 11.9851 4.00291ZM8.01766 11C8.08396 9.13314 8.33431 7.41167 8.72334 6.00094C8.87366 5.45584 9.04762 4.94639 9.24523 4.48694C6.48462 5.49946 4.43722 7.9901 4.06189 11H8.01766ZM4.06189 13H8.01766C8.09487 15.1737 8.42177 17.1555 8.93 18.6802C9.02641 18.9694 9.13134 19.2483 9.24522 19.5131C6.48461 18.5005 4.43722 16.0099 4.06189 13ZM10.019 13H13.981C13.9045 14.9972 13.6027 16.7574 13.1726 18.0477C12.9206 18.8038 12.6425 19.3436 12.3823 19.6737C12.2545 19.8359 12.1506 19.9225 12.0814 19.9649C12.0485 19.9852 12.0264 19.9935 12.0153 19.9969C12.0049 20.0001 11.9999 20 11.9999 20C11.9999 20 11.9948 20 11.9847 19.9969C11.9736 19.9935 11.9515 19.9852 11.9186 19.9649C11.8494 19.9225 11.7455 19.8359 11.6177 19.6737C11.3575 19.3436 11.0794 18.8038 10.8274 18.0477C10.3973 16.7574 10.0955 14.9972 10.019 13ZM15.9823 13C15.9051 15.1737 15.5782 17.1555 15.07 18.6802C14.9736 18.9694 14.8687 19.2483 14.7548 19.5131C17.5154 18.5005 19.5628 16.0099 19.9381 13H15.9823ZM19.9381 11C19.5628 7.99009 17.5154 5.49946 14.7548 4.48694C14.9524 4.94639 15.1263 5.45584 15.2767 6.00094C15.6657 7.41167 15.916 9.13314 15.9823 11H19.9381Z\" fill=\"currentColor\"></path></svg>",
#                     "required_features": [
#                         "search"
#                     ],
#                     "required_models": [],
#                     "required_conversation_modes": [
#                         "primary_assistant"
#                     ],
#                     "allow_in_temporary_chat": True,
#                     "composer_bar_button_info": None,
#                     "suggested_prompt": None,
#                     "regex_matches": None
#                 },
#                 {
#                     "system_hint": "reason",
#                     "name": "推理",
#                     "description": "使用 o3-mini",
#                     "logo": "<svg fill=\"none\" viewBox=\"0 0 24 24\" xmlns=\"http://www.w3.org/2000/svg\"><path d=\"m12 3c-3.585 0-6.5 2.9225-6.5 6.5385 0 2.2826 1.162 4.2913 2.9248 5.4615h7.1504c1.7628-1.1702 2.9248-3.1789 2.9248-5.4615 0-3.6159-2.915-6.5385-6.5-6.5385zm2.8653 14h-5.7306v1h5.7306v-1zm-1.1329 3h-3.4648c0.3458 0.5978 0.9921 1 1.7324 1s1.3866-0.4022 1.7324-1zm-5.6064 0c0.44403 1.7252 2.0101 3 3.874 3s3.43-1.2748 3.874-3c0.5483-0.0047 0.9913-0.4506 0.9913-1v-2.4593c2.1969-1.5431 3.6347-4.1045 3.6347-7.0022 0-4.7108-3.8008-8.5385-8.5-8.5385-4.6992 0-8.5 3.8276-8.5 8.5385 0 2.8977 1.4378 5.4591 3.6347 7.0022v2.4593c0 0.5494 0.44301 0.9953 0.99128 1z\" clip-rule=\"evenodd\" fill=\"currentColor\" fill-rule=\"evenodd\"/></svg>",
#                     "required_features": [],
#                     "required_models": [
#                         "o1",
#                         "o3-mini"
#                     ],
#                     "required_conversation_modes": [
#                         "primary_assistant"
#                     ],
#                     "allow_in_temporary_chat": True,
#                     "composer_bar_button_info": {
#                         "disabled_text": "推理不可用",
#                         "tooltip_text": "思考后再回复",
#                         "announcement_key": "",
#                         "nux_title": "",
#                         "nux_description": "ChatGPT 可以先思考更长时间再回复，以便更好地回答您的重大问题。",
#                         "rate_limit_reached_text": None
#                     },
#                     "suggested_prompt": None,
#                     "regex_matches": None
#                 },
#                 {
#                     "system_hint": "canvas",
#                     "name": "画布",
#                     "description": "在写作和代码方面开展协作",
#                     "logo": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\" xmlns=\"http://www.w3.org/2000/svg\"><path d=\"M2.5 5.5C4.3 5.2 5.2 4 5.5 2.5C5.8 4 6.7 5.2 8.5 5.5C6.7 5.8 5.8 7 5.5 8.5C5.2 7 4.3 5.8 2.5 5.5Z\" fill=\"currentColor\" stroke=\"currentColor\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/><path d=\"M5.66282 16.5231L5.18413 19.3952C5.12203 19.7678 5.09098 19.9541 5.14876 20.0888C5.19933 20.2067 5.29328 20.3007 5.41118 20.3512C5.54589 20.409 5.73218 20.378 6.10476 20.3159L8.97693 19.8372C9.72813 19.712 10.1037 19.6494 10.4542 19.521C10.7652 19.407 11.0608 19.2549 11.3343 19.068C11.6425 18.8575 11.9118 18.5882 12.4503 18.0497L20 10.5C21.3807 9.11929 21.3807 6.88071 20 5.5C18.6193 4.11929 16.3807 4.11929 15 5.5L7.45026 13.0497C6.91175 13.5882 6.6425 13.8575 6.43197 14.1657C6.24513 14.4392 6.09299 14.7348 5.97903 15.0458C5.85062 15.3963 5.78802 15.7719 5.66282 16.5231Z\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/><path d=\"M14.5 7L18.5 11\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/></svg>",
#                     "required_features": [
#                         "canvas"
#                     ],
#                     "required_models": [],
#                     "required_conversation_modes": [],
#                     "allow_in_temporary_chat": False,
#                     "composer_bar_button_info": None,
#                     "suggested_prompt": {
#                         "theme": "#AF52DE",
#                         "title": "画布",
#                         "subtitle": "写作和编程",
#                         "sort_order": 3,
#                         "badge": None
#                     },
#                     "regex_matches": None
#                 },
#                 {
#                     "system_hint": "research",
#                     "name": "深入研究",
#                     "description": "对任何主题都有详细的见解",
#                     "logo": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\" fill=\"none\"><path fill=\"currentColor\" fill-rule=\"evenodd\" d=\"M12.47 15.652a1 1 0 0 1 1.378.318l2.5 4a1 1 0 1 1-1.696 1.06l-2.5-4a1 1 0 0 1 .318-1.378Z\" clip-rule=\"evenodd\"/><path fill=\"currentColor\" fill-rule=\"evenodd\" d=\"M11.53 15.652a1 1 0 0 1 .318 1.378l-2.5 4a1 1 0 0 1-1.696-1.06l2.5-4a1 1 0 0 1 1.378-.318ZM17.824 4.346a.5.5 0 0 0-.63-.321l-.951.309a1 1 0 0 0-.642 1.26l1.545 4.755a1 1 0 0 0 1.26.642l.95-.309a.5.5 0 0 0 .322-.63l-1.854-5.706Zm-1.248-2.223a2.5 2.5 0 0 1 3.15 1.605l1.854 5.706a2.5 2.5 0 0 1-1.605 3.15l-.951.31a2.992 2.992 0 0 1-2.443-.265l-2.02.569a1 1 0 1 1-.541-1.926l1.212-.34-1.353-4.163L5 10.46a1 1 0 0 0-.567 1.233l.381 1.171a1 1 0 0 0 1.222.654l3.127-.88a1 1 0 1 1 .541 1.926l-3.127.88a3 3 0 0 1-3.665-1.961l-.38-1.172a3 3 0 0 1 1.7-3.697l9.374-3.897a3 3 0 0 1 2.02-2.285l.95-.31Z\" clip-rule=\"evenodd\"/><path fill=\"currentColor\" fill-rule=\"evenodd\" d=\"M12 12.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3ZM8.5 14a3.5 3.5 0 1 1 7 0 3.5 3.5 0 0 1-7 0Z\" clip-rule=\"evenodd\"/></svg>",
#                     "required_features": [],
#                     "required_models": [],
#                     "required_conversation_modes": [
#                         "primary_assistant"
#                     ],
#                     "allow_in_temporary_chat": False,
#                     "composer_bar_button_info": {
#                         "disabled_text": "深入研究不可用",
#                         "tooltip_text": "对任何主题都有详细的见解",
#                         "announcement_key": "oai/apps/hasSeenComposerCaterpillarButtonTooltip",
#                         "nux_title": "您的个人研究员",
#                         "nux_description": "使用 ChatGPT 来研究购物、大概念、科学问题等内容。[了解更多](https://openai.com/index/introducing-deep-research/)",
#                         "rate_limit_reached_text": "本月限额已用完"
#                     },
#                     "suggested_prompt": {
#                         "theme": "#0088FF",
#                         "title": "深入研究",
#                         "subtitle": "探索宏大主题",
#                         "sort_order": 1,
#                         "badge": "新"
#                     },
#                     "regex_matches": None
#                 }
#             ]
#         }
#     return Response(content=json.dumps(system_hints, indent=4), media_type="application/json")


@app.post("/backend-api/edge")
async def edge():
    return Response(status_code=204)


if no_sentinel:
    openai_sentinel_tokens_cache = {}
    openai_sentinel_cookies_cache = {}

    @app.post("/backend-api/sentinel/chat-requirements")
    async def sentinel_chat_conversations(request: Request):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        req_token = await get_real_req_token(token)
        access_token = await verify_token(req_token)
        fp = get_fp(req_token).copy()
        proxy_url = fp.pop("proxy_url", None)
        impersonate = fp.pop("impersonate", "safari15_3")
        user_agent = fp.get("user-agent",
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0")

        host_url = random.choice(chatgpt_base_url_list) if chatgpt_base_url_list else "https://chatgpt.com"
        proof_token = None
        turnstile_token = None

        # headers = {
        #     key: value for key, value in request.headers.items()
        #     if (key.lower() not in ["host", "origin", "referer", "priority", "sec-ch-ua-platform", "sec-ch-ua",
        #                             "sec-ch-ua-mobile", "oai-device-id"] and key.lower() not in headers_reject_list)
        # }
        headers = {
            key: value for key, value in request.headers.items()
            if (key.lower() in headers_accept_list)
        }
        headers.update(fp)
        headers.update({"authorization": f"Bearer {access_token}"})
        session_id = hashlib.md5(req_token.encode()).hexdigest()
        proxy_url = proxy_url.replace("{}", session_id) if proxy_url else None
        client = Client(proxy=proxy_url, impersonate=impersonate)
        if sentinel_proxy_url_list:
            sentinel_proxy_url = random.choice(sentinel_proxy_url_list).replace("{}", session_id) if sentinel_proxy_url_list else None
            clients = Client(proxy=sentinel_proxy_url, impersonate=impersonate)
        else:
            clients = client

        try:
            config = get_config(user_agent, session_id)
            p = get_requirements_token(config)
            data = {'p': p}
            for cookie in openai_sentinel_cookies_cache.get(req_token, []):
                clients.session.cookies.set(**cookie)
            r = await clients.post(f'{host_url}/backend-api/sentinel/chat-requirements', headers=headers, json=data, timeout=10)
            oai_sc = r.cookies.get("oai-sc")
            if oai_sc:
                openai_sentinel_cookies_cache[req_token] = [{"name": "oai-sc", "value": oai_sc}]
            if r.status_code != 200:
                raise HTTPException(status_code=r.status_code, detail="Failed to get chat requirements")
            resp = r.json()
            turnstile = resp.get('turnstile', {})
            turnstile_required = turnstile.get('required')
            if turnstile_required:
                turnstile_dx = turnstile.get("dx")
                try:
                    if turnstile_solver_url:
                        res = await client.post(turnstile_solver_url,
                                                json={"url": "https://chatgpt.com", "p": p, "dx": turnstile_dx, "ua": user_agent})
                        turnstile_token = res.json().get("t")
                except Exception as e:
                    logger.info(f"Turnstile ignored: {e}")

            proofofwork = resp.get('proofofwork', {})
            proofofwork_required = proofofwork.get('required')
            if proofofwork_required:
                proofofwork_diff = proofofwork.get("difficulty")
                proofofwork_seed = proofofwork.get("seed")
                proof_token, solved = await run_in_threadpool(
                    get_answer_token, proofofwork_seed, proofofwork_diff, config
                )
                if not solved:
                    raise HTTPException(status_code=403, detail="Failed to solve proof of work")
            chat_token = resp.get('token')

            openai_sentinel_tokens_cache[req_token] = {
                "chat_token": chat_token,
                "proof_token": proof_token,
                "turnstile_token": turnstile_token
            }
        except Exception as e:
            logger.error(f"Sentinel failed: {e}")

        return {
            "arkose": {
                "dx": None,
                "required": False
            },
            "persona": "chatgpt-paid",
            "proofofwork": {
                "difficulty": None,
                "required": False,
                "seed": None
            },
            "token": str(uuid.uuid4()),
            "turnstile": {
                "dx": None,
                "required": False
            }
        }


    @app.post("/backend-alt/conversation")
    @app.post("/backend-api/conversation")
    async def chat_conversations(request: Request):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        req_token = await get_real_req_token(token)
        access_token = await verify_token(req_token)
        fp = get_fp(req_token).copy()
        proxy_url = fp.pop("proxy_url", None)
        impersonate = fp.pop("impersonate", "safari15_3")
        user_agent = fp.get("user-agent",
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0")

        host_url = random.choice(chatgpt_base_url_list) if chatgpt_base_url_list else "https://chatgpt.com"
        proof_token = None
        turnstile_token = None

        # headers = {
        #     key: value for key, value in request.headers.items()
        #     if (key.lower() not in ["host", "origin", "referer", "priority", "sec-ch-ua-platform", "sec-ch-ua",
        #                             "sec-ch-ua-mobile", "oai-device-id"] and key.lower() not in headers_reject_list)
        # }
        headers = {
            key: value for key, value in request.headers.items()
            if (key.lower() in headers_accept_list)
        }
        headers.update(fp)
        headers.update({"authorization": f"Bearer {access_token}"})

        try:
            session_id = hashlib.md5(req_token.encode()).hexdigest()
            proxy_url = proxy_url.replace("{}", session_id) if proxy_url else None
            client = Client(proxy=proxy_url, impersonate=impersonate)
            if sentinel_proxy_url_list:
                sentinel_proxy_url = random.choice(sentinel_proxy_url_list).replace("{}", session_id) if sentinel_proxy_url_list else None
                clients = Client(proxy=sentinel_proxy_url, impersonate=impersonate)
            else:
                clients = client

            sentinel_tokens = openai_sentinel_tokens_cache.get(req_token, {})
            openai_sentinel_tokens_cache.pop(req_token, None)
            if not sentinel_tokens:
                config = get_config(user_agent, session_id)
                p = get_requirements_token(config)
                data = {'p': p}
                r = await clients.post(f'{host_url}/backend-api/sentinel/chat-requirements', headers=headers, json=data,
                                       timeout=10)
                resp = r.json()
                turnstile = resp.get('turnstile', {})
                turnstile_required = turnstile.get('required')
                if turnstile_required:
                    turnstile_dx = turnstile.get("dx")
                    try:
                        if turnstile_solver_url:
                            res = await client.post(turnstile_solver_url,
                                                    json={"url": "https://chatgpt.com", "p": p, "dx": turnstile_dx, "ua": user_agent})
                            turnstile_token = res.json().get("t")
                    except Exception as e:
                        logger.info(f"Turnstile ignored: {e}")

                proofofwork = resp.get('proofofwork', {})
                proofofwork_required = proofofwork.get('required')
                if proofofwork_required:
                    proofofwork_diff = proofofwork.get("difficulty")
                    proofofwork_seed = proofofwork.get("seed")
                    proof_token, solved = await run_in_threadpool(
                        get_answer_token, proofofwork_seed, proofofwork_diff, config
                    )
                    if not solved:
                        raise HTTPException(status_code=403, detail="Failed to solve proof of work")
                chat_token = resp.get('token')
                headers.update({
                    "openai-sentinel-chat-requirements-token": chat_token,
                    "openai-sentinel-proof-token": proof_token,
                    "openai-sentinel-turnstile-token": turnstile_token,
                })
            else:
                headers.update({
                    "openai-sentinel-chat-requirements-token": sentinel_tokens.get("chat_token", ""),
                    "openai-sentinel-proof-token": sentinel_tokens.get("proof_token", ""),
                    "openai-sentinel-turnstile-token": sentinel_tokens.get("turnstile_token", "")
                })
        except Exception as e:
            logger.error(f"Sentinel failed: {e}")
            return Response(status_code=403, content="Sentinel failed")

        params = dict(request.query_params)
        data = await request.body()
        request_cookies = dict(request.cookies)

        async def c_close(client, clients):
            if client:
                await client.close()
                del client
            if clients:
                await clients.close()
                del clients

        history = True
        try:
            req_json = json.loads(data)
            history = not req_json.get("history_and_training_disabled", False)
        except Exception:
            pass
        if force_no_history:
            history = False
            req_json = json.loads(data)
            req_json["history_and_training_disabled"] = True
            data = json.dumps(req_json).encode("utf-8")

        background = BackgroundTask(c_close, client, clients)
        r = await client.post_stream(f"{host_url}{request.url.path}", params=params, headers=headers,
                                     cookies=request_cookies, data=data, stream=True, allow_redirects=False)
        rheaders = r.headers
        logger.info(f"Request token: {req_token}")
        logger.info(f"Request proxy: {proxy_url}")
        logger.info(f"Request UA: {user_agent}")
        logger.info(f"Request impersonate: {impersonate}")
        if x_sign:
            rheaders.update({"x-sign": x_sign})
        if 'stream' in rheaders.get("content-type", ""):
            conv_key = r.cookies.get("conv_key", "")
            response = StreamingResponse(content_generator(r, token, history), headers=rheaders,
                                         media_type=r.headers.get("content-type", ""), background=background)
            response.set_cookie("conv_key", value=conv_key)
            return response
        else:
            return Response(content=(await r.atext()), headers=rheaders, media_type=rheaders.get("content-type"),
                            status_code=r.status_code, background=background)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH", "TRACE"])
async def reverse_proxy(request: Request, path: str):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if len(token) != 45 and not token.startswith("eyJhbGciOi"):
        for banned_path in banned_paths:
            if re.match(banned_path, path):
                raise HTTPException(status_code=403, detail="Forbidden")

    for chatgpt_path in chatgpt_paths:
        if re.match(chatgpt_path, path):
            return await chatgpt_html(request)

    for redirect_path in redirect_paths:
        if re.match(redirect_path, path):
            redirect_url = str(request.base_url)
            response = RedirectResponse(url=f"{redirect_url}login", status_code=302)
            return response

    return await chatgpt_reverse_proxy(request, path)
