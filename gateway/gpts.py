import json
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import RedirectResponse, Response

from app import app
from gateway.chatgpt import chatgpt_html
from gateway.login import login_html
from utils.kv_utils import set_value_for_key_list

with open("templates/gpts_context.json", "r", encoding="utf-8") as f:
    gpts_context = json.load(f)


@app.get("/gpts")
async def get_gpts(request: Request):
    return await chatgpt_html(request)

@app.get("/gpts.data")
async def get_gpts(request: Request):
    referrer = request.headers.get("referer", "")
    response_str = '[{"_1":2},"routes/gpts._index",{"_3":4},"data",{"_5":6,"_7":8},"kind","store","referrer","https://chatgpt.com/"]'
    response_str = response_str.replace("https://chatgpt.com/", referrer)
    return Response(content=response_str, media_type="text/x-script; charset=utf-8")


@app.get("/g/g-{gizmo_id}")
async def get_gizmo_json(request: Request, gizmo_id: str):
    params = request.query_params
    if params.get("_routes") == "routes/g.$gizmoId._index":
        # 安全：未登录访问应返回登录页而非 500。
        # 原实现直接 len(token)/token.startswith(...) 对 None 调用会抛 TypeError。
        token = request.cookies.get("token") or ""
        if not token:
            return await login_html(request)
        if len(token) != 45 and not token.startswith("eyJhbGciOi"):
            token = quote(token)
        user_gpts_context = gpts_context.copy()
        set_value_for_key_list(user_gpts_context, "accessToken", token)
        response_str = json.dumps(user_gpts_context, separators=(',', ':'), ensure_ascii=False)
        return Response(content=response_str, media_type="text/x-script; charset=utf-8")
    else:
        return await chatgpt_html(request)
