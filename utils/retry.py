from utils.Logger import Logger


async def async_retry(func, *args, max_retries=3, **kwargs):
    for attempt in range(max_retries):
        try:
            result = await func(*args, **kwargs)
            return result
        except Exception as e:
            Logger.info(f"{func.__name__} 运行出错: {e}, 正在重试第 {attempt + 1} 次...")
    else:
        Logger.info(f"{func.__name__} 重试 {max_retries} 次后仍然失败.")


def retry(func, *args, max_retries=3, **kwargs):
    for attempt in range(max_retries):
        try:
            result = func(*args, **kwargs)
            return result
        except Exception as e:
            Logger.info(f"{func.__name__} 运行出错: {e}, 正在重试第 {attempt + 1} 次...")
    else:
        Logger.info(f"{func.__name__} 重试 {max_retries} 次后仍然失败.")