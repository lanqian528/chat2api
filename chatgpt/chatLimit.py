import asyncio
import threading
import time
from datetime import datetime

from utils.Logger import logger

#  开启线程锁
lock = threading.Lock()
# 对于密钥的限制
limit_access_token = {}


async def check_isLimit(e, access_token):
    if e.status_code == 429:
        clearTime = time.time() + e.detail.get('clears_in')
        clearDate = datetime.fromtimestamp(clearTime)
        initial_access_list(access_token, clearTime, clearDate)


async def initial_access_list(key, clear_time):
    with lock:
        limit_access_token[key] = clear_time
    logger.info(
        f"{key}: Reached 429 limit, will be cleared at {datetime.fromtimestamp(clear_time).replace(second=0, microsecond=0)}")


async def remove_refresh_list(key):
    with lock:
        if key in limit_access_token:
            limit_access_token.pop(key)
            logger.info(f"Removed limit for {key[:40]}.")
        else:
            logger.info(f"Access token {key[:40]} not found in limit_access_token.")


async def handle_request_limit(request_data, access_token):
    if "gpt-4" in request_data.get("model") and access_token in limit_access_token:
        is_clear = limit_access_token[access_token] < time.time()
        if is_clear:
            await remove_refresh_list(access_token)
        else:
            clear_date = datetime.fromtimestamp(limit_access_token[access_token])
            logger.info(f"Request limit exceeded. "
                        f"You can continue with the default model now, "
                        f"or try again after {clear_date.replace(second=0, microsecond=0)}")
            return f"Request limit exceeded. You can continue with the default model now, or try again after {clear_date.replace(second=0, microsecond=0)}"
    return None


# 清理函数，用于删除长时间未使用的键值对
def clean_dict():
    logger.info("开始执行清理过期的limit_access_token......")
    current_time = time.time()
    keys_to_remove = [key for key, clear_time in limit_access_token.items() if clear_time < current_time]
    for key in keys_to_remove:
        with lock:
            del limit_access_token[key]


# 后台任务，定期执行清理函数
async def clean_background_task():
    while True:
        clean_dict()
        # 一天执行一次，防止limit_access_token过多
        await asyncio.sleep(3600 * 24)
