import os
from dotenv import load_dotenv

load_dotenv()

authorization = os.getenv('AUTHORIZATION')
free35_base_url = os.getenv('FREE35_BASE_URL', 'https://chat.openai.com/backend-anon')
chatgpt_base_url = os.getenv('CHATGPT_BASE_URL', 'https://chat.openai.com/backend-api')
history_disabled_str = os.getenv('HISTORY_DISABLED', 'false')
history_disabled = history_disabled_str.lower() in ['true', '1', 't', 'y', 'yes']
proxy_url = os.getenv('PROXY_URL')
