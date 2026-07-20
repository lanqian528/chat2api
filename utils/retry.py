import asyncio
import time

from fastapi import HTTPException

from utils.Logger import logger
from utils.configs import retry_times

RETRYABLE_STATUS_CODES = {408, 500, 502, 503, 504}
BASE_RETRY_DELAY_SECONDS = 0.5
MAX_RETRY_DELAY_SECONDS = 4


def should_retry_http_exception(status_code):
    return status_code in RETRYABLE_STATUS_CODES


def get_retry_delay(attempt):
    delay = BASE_RETRY_DELAY_SECONDS * (2 ** attempt)
    return min(delay, MAX_RETRY_DELAY_SECONDS)


async def async_retry(func, *args, max_retries=retry_times, **kwargs):
    for attempt in range(max_retries + 1):
        try:
            result = await func(*args, **kwargs)
            return result
        except HTTPException as e:
            should_retry = should_retry_http_exception(e.status_code)
            if attempt == max_retries or not should_retry:
                logger.error(f"Throw an exception {e.status_code}, {e.detail}")
                if e.status_code == 500:
                    raise HTTPException(status_code=500, detail="Server error")
                raise HTTPException(status_code=e.status_code, detail=e.detail)
            delay = get_retry_delay(attempt)
            logger.info(
                f"Retry {attempt + 1} status code {e.status_code}, {e.detail}. "
                f"Retrying in {delay:.1f}s..."
            )
            await asyncio.sleep(delay)


def retry(func, *args, max_retries=retry_times, **kwargs):
    for attempt in range(max_retries + 1):
        try:
            result = func(*args, **kwargs)
            return result
        except HTTPException as e:
            should_retry = should_retry_http_exception(e.status_code)
            if attempt == max_retries or not should_retry:
                logger.error(f"Throw an exception {e.status_code}, {e.detail}")
                if e.status_code == 500:
                    raise HTTPException(status_code=500, detail="Server error")
                raise HTTPException(status_code=e.status_code, detail=e.detail)
            delay = get_retry_delay(attempt)
            logger.error(
                f"Retry {attempt + 1} status code {e.status_code}, {e.detail}. "
                f"Retrying in {delay:.1f}s..."
            )
            time.sleep(delay)
