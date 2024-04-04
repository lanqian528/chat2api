import os

chatgpt_base_url = os.environ.get('CHATGPT_BASE_URL', 'https://chat.openai.com/backend-anon')
history_disabled = os.environ.get('HISTORY_DISABLED', True)
proxy_url = os.environ.get('PROXY_URL', None)
