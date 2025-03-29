import os
from fastapi import Request
from fastapi.responses import HTMLResponse

from app import app, templates


@app.get("/login", response_class=HTMLResponse)
async def login_html(request: Request):
    site_password = os.environ.get('SITE_PASSWORD', '')
    return templates.TemplateResponse("login.html", {
        "request": request,
        "site_password": site_password
    })
