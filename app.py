import asyncio

import uvicorn

from chat2api import app
from chatgpt.chatLimit import clean_background_task

log_config = uvicorn.config.LOGGING_CONFIG
default_format = "%(asctime)s | %(levelname)s | %(message)s"
access_format = r'%(asctime)s | %(levelname)s | %(client_addr)s: %(request_line)s %(status_code)s'
log_config["formatters"]["default"]["fmt"] = default_format
log_config["formatters"]["access"]["fmt"] = access_format


# 在应用启动时启动后台任务
@app.on_event("startup")
async def startup_event():
    clean_task = asyncio.create_task(clean_background_task())


uvicorn.run("chat2api:app", host="0.0.0.0", port=5005)
