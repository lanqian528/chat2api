import os
from dotenv import load_dotenv

from utils.Logger import Logger

load_dotenv()

authorization = os.getenv('AUTHORIZATION').replace(' ', '')
free35_base_url = os.getenv('FREE35_BASE_URL', 'https://chat.openai.com/backend-anon').replace(' ', '')
chatgpt_base_url = os.getenv('CHATGPT_BASE_URL', 'https://chat.openai.com/backend-api').replace(' ', '')
history_disabled_str = os.getenv('HISTORY_DISABLED', 'false').replace(' ', '')
history_disabled = history_disabled_str.lower() in ['true', '1', 't', 'y', 'yes']
proxy_url = os.getenv('PROXY_URL').replace(' ', '')


authorization_list = authorization.split(',') if authorization else [authorization]
free35_base_url_list = free35_base_url.split(',') if free35_base_url else [free35_base_url]
chatgpt_base_url_list = chatgpt_base_url.split(',') if chatgpt_base_url else [chatgpt_base_url]
proxy_url_list = proxy_url.split(',') if proxy_url else [proxy_url]

Logger.info("Environment variables (no AUTHORIZATION):")
Logger.info("FREE35_BASE_URL:       " + str(free35_base_url_list))
Logger.info("CHATGPT_BASE_URL:      " + str(chatgpt_base_url_list))
Logger.info("PROXY_URL:             " + str(proxy_url_list))