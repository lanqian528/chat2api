import threading
import time
from datetime import datetime
from utils.Logger import logger

#  开启线程锁
lock = threading.Lock()
# 对于密钥的限制
limit_access_token = {}


def check_isLimit(detail, access_token):
    if detail.get('clears_in'):
        clearTime = time.time() + detail.get('clears_in')
        initial_access_list(access_token, clearTime)


def initial_access_list(key, clear_time):
    with lock:
        limit_access_token[key] = clear_time
    logger.info(
        f"{key[:40]}: Reached 429 limit, will be cleared at {datetime.fromtimestamp(clear_time).replace(second=0, microsecond=0)}")


def remove_refresh_list(key):
    with lock:
        if key in limit_access_token:
            limit_access_token.pop(key)
            logger.info(f"Removed limit for {key[:40]}.")
        else:
            logger.info(f"Access token: {key[:40]} not found in limit_access_token.")


async def handle_request_limit(request_data, access_token):
    try:
        if "gpt-4" in request_data.get("model", "gpt-3.5-turbo") and access_token in limit_access_token:
            limit_time = limit_access_token[access_token]
            is_clear = limit_time < time.time()
            if is_clear:
                remove_refresh_list(access_token)
            else:
                clear_date = datetime.fromtimestamp(limit_time).replace(second=0, microsecond=0)
                logger.info(f"Request limit exceeded. "
                            f"You can continue with the default model now, "
                            f"or try again after {clear_date}")
                return f"Request limit exceeded. You can continue with the default model now, or try again after {clear_date}"
        return None
    except Exception as e:
        logger.error(e)
        return None


# 清理函数，用于删除长时间未使用的键值对
def clean_dict():
    logger.info(f"==========================================")
    logger.info("开始执行清理过期的limit_access_token......")
    current_time = time.time()
    keys_to_remove = [key for key, clear_time in limit_access_token.items() if clear_time < current_time]
    for key in keys_to_remove:
        with lock:
            del limit_access_token[key]
