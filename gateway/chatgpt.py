import json
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse

from app import app, templates
from gateway.login import login_html
from utils.kv_utils import set_value_for_key
import utils.configs as configs
import utils.globals as globals

with open("templates/chatgpt_context.json", "r", encoding="utf-8") as f:
    chatgpt_context = json.load(f)


@app.get("/", response_class=HTMLResponse)
async def chatgpt_html(request: Request):
    token = request.query_params.get("token")
    if not token:
        token = request.cookies.get("token")
    if not token:
        return await login_html(request)

    if len(token) != 45 and not token.startswith("eyJhbGciOi"):
        token = quote(token)
        if configs.auto_seed == False and token not in globals.seed_map.keys():
            return await login_html(request)

    user_remix_context = chatgpt_context.copy()
    set_value_for_key(user_remix_context, "user", {"id": "user-chatgpt"})
    set_value_for_key(user_remix_context, "accessToken", token)

    response = templates.TemplateResponse("chatgpt.html", {"request": request, "remix_context": user_remix_context})
    response.set_cookie("token", value=token, expires="Thu, 01 Jan 2099 00:00:00 GMT")
    return response
