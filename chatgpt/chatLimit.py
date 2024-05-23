import threading
import time
from datetime import datetime
from utils.Logger import logger

lock = threading.Lock()
limit_access_token = {}


def check_isLimit(detail, access_token):
    if detail.get('clears_in'):
        clear_time = time.time() + detail.get('clears_in')
        initial_access_list(access_token, clear_time)


def initial_access_list(key, clear_time):
    with lock:
        limit_access_token[key] = clear_time
    logger.info(f"{key[:40]}: Reached 429 limit, will be cleared at {datetime.fromtimestamp(clear_time).replace(second=0, microsecond=0)}")


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
                result = f"Request limit exceeded. You can continue with the default model now, or try again after {clear_date}"
                logger.info(result)
                return result
        return None
    except Exception as e:
        logger.error(e)
        return None


def clean_dict():
    logger.info("-" * 60)
    logger.info("Start to clean limit_access_token......")
    current_time = time.time()
    keys_to_remove = [key for key, clear_time in limit_access_token.items() if clear_time < current_time]
    for key in keys_to_remove:
        with lock:
            del limit_access_token[key]
