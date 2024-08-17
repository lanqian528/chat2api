import threading
import time
from datetime import datetime

from utils.Logger import logger

limit_details = {}


def check_is_limit(detail, token, model):
    if token and isinstance(detail, dict) and detail.get('clears_in'):
        clear_time = int(time.time()) + detail.get('clears_in')
        limit_details.setdefault(token, {})[model] = clear_time
        logger.info(f"{token[:40]}: Reached {model} limit, will be cleared at {datetime.fromtimestamp(clear_time).replace(microsecond=0)}")


async def handle_request_limit(token, model):
    try:
        if limit_details.get(token) and model in limit_details[token]:
            limit_time = limit_details[token][model]
            is_limit = limit_time > int(time.time())
            if is_limit:
                clear_date = datetime.fromtimestamp(limit_time).replace(microsecond=0)
                result = f"Request limit exceeded. You can continue with the default model now, or try again after {clear_date}"
                logger.info(result)
                return result
            else:
                del limit_details[token][model]
                return None
    except KeyError as e:
        logger.error(f"Key error: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return None
