import os

from dotenv import load_dotenv

from utils.Logger import logger

load_dotenv(encoding="ascii")


def is_true(x):
    if isinstance(x, bool):
        return x
    if isinstance(x, str):
        return x.lower() in ['true', '1', 't', 'y', 'yes']
    elif isinstance(x, int):
        return x == 1
    else:
        return False


api_prefix = os.getenv('API_PREFIX', None)
authorization = os.getenv('AUTHORIZATION', '').replace(' ', '')
chatgpt_base_url = os.getenv('CHATGPT_BASE_URL', 'https://chatgpt.com').replace(' ', '')
arkose_token_url = os.getenv('ARKOSE_TOKEN_URL', '').replace(' ', '')
proxy_url = os.getenv('PROXY_URL', '').replace(' ', '')
history_disabled = is_true(os.getenv('HISTORY_DISABLED', True))
pow_difficulty = os.getenv('POW_DIFFICULTY', '000032')
retry_times = int(os.getenv('RETRY_TIMES', 3))
enable_gateway = is_true(os.getenv('ENABLE_GATEWAY', True))
conversation_only = is_true(os.getenv('CONVERSATION_ONLY', False))
enable_limit = is_true(os.getenv('ENABLE_LIMIT', True))
limit_status_code = os.getenv('LIMIT_STATUS_CODE', 429)
upload_by_url = is_true(os.getenv('UPLOAD_BY_URL', False))
check_model = is_true(os.getenv('CHECK_MODEL', False))

authorization_list = authorization.split(',') if authorization else []
chatgpt_base_url_list = chatgpt_base_url.split(',') if chatgpt_base_url else []
arkose_token_url_list = arkose_token_url.split(',') if arkose_token_url else []
proxy_url_list = proxy_url.split(',') if proxy_url else []

logger.info("-" * 60)
logger.info("Chat2Api v1.1.11 | https://github.com/lanqian528/chat2api")
logger.info("-" * 60)
logger.info("Environment variables:")
logger.info("API_PREFIX:        " + str(api_prefix))
logger.info("AUTHORIZATION:     " + str(authorization_list))
logger.info("CHATGPT_BASE_URL:  " + str(chatgpt_base_url_list))
logger.info("ARKOSE_TOKEN_URL:  " + str(arkose_token_url_list))
logger.info("PROXY_URL:         " + str(proxy_url_list))
logger.info("HISTORY_DISABLED:  " + str(history_disabled))
logger.info("POW_DIFFICULTY:    " + str(pow_difficulty))
logger.info("RETRY_TIMES:       " + str(retry_times))
logger.info("ENABLE_GATEWAY:    " + str(enable_gateway))
logger.info("CONVERSATION_ONLY: " + str(conversation_only))
logger.info("ENABLE_LIMIT:      " + str(enable_limit))
logger.info("UPLOAD_BY_URL:     " + str(upload_by_url))
logger.info("CHECK_MODEL:     " + str(check_model))
logger.info("-" * 60)
