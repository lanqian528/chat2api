import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler

from chat2api import app
from chatgpt.chatLimit import clean_dict

log_config = uvicorn.config.LOGGING_CONFIG
default_format = "%(asctime)s | %(levelname)s | %(message)s"
access_format = r'%(asctime)s | %(levelname)s | %(client_addr)s: %(request_line)s %(status_code)s'
log_config["formatters"]["default"]["fmt"] = default_format
log_config["formatters"]["access"]["fmt"] = access_format

scheduler = BackgroundScheduler()


# 用于自动更新限制access_token的字典
# 避免过多access_token没有销毁,而堆积
@app.on_event("startup")
async def app_start():
    scheduler.add_job(id='updateLimit_run', func=clean_dict, trigger='cron', hour=3, minute=0)
    scheduler.start()


uvicorn.run("chat2api:app", host="0.0.0.0", port=5005)
