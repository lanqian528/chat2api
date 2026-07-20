import ast
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
admin_password = os.getenv('ADMIN_PASSWORD', None)
# 管理后台 IP 白名单（逗号分隔，支持单 IP / CIDR / 'trust_proxy'）
# 空串 = 不启用（允许所有 IP 访问登录页；真正 API 仍受 ADMIN_PASSWORD 保护）
# 示例: ADMIN_IP_WHITELIST="1.2.3.4,10.0.0.0/8,192.168.1.0/24"
admin_ip_whitelist_raw = os.getenv('ADMIN_IP_WHITELIST', '').replace(' ', '')
admin_ip_whitelist = [x for x in admin_ip_whitelist_raw.split(',') if x]
# 是否信任 X-Forwarded-For 头（仅在 CF / Nginx 反代场景开启，否则可被伪造绕过）
admin_trust_proxy = os.getenv('ADMIN_TRUST_PROXY', '').lower() in ('true', '1', 'yes')
chatgpt_base_url = os.getenv('CHATGPT_BASE_URL', 'https://chatgpt.com').replace(' ', '')
auth_key = os.getenv('AUTH_KEY', None)
x_sign = os.getenv('X_SIGN', None)

ark0se_token_url = os.getenv('ARK' + 'OSE_TOKEN_URL', '').replace(' ', '')
if not ark0se_token_url:
    ark0se_token_url = os.getenv('ARK0SE_TOKEN_URL', None)
proxy_url = os.getenv('PROXY_URL', '').replace(' ', '')
sentinel_proxy_url = os.getenv('SENTINEL_PROXY_URL', None)
export_proxy_url = os.getenv('EXPORT_PROXY_URL', None)
file_host = os.getenv('FILE_HOST', None)
voice_host = os.getenv('VOICE_HOST', None)
impersonate_list_str = os.getenv('IMPERSONATE', '[]')
user_agents_list_str = os.getenv('USER_AGENTS', '[]')
device_tuple_str = os.getenv('DEVICE_TUPLE', '()')
browser_tuple_str = os.getenv('BROWSER_TUPLE', '()')
platform_tuple_str = os.getenv('PLATFORM_TUPLE', '()')

cf_file_url = os.getenv('CF_FILE_URL', None)
turnstile_solver_url = os.getenv('TURNSTILE_SOLVER_URL', None)

history_disabled = is_true(os.getenv('HISTORY_DISABLED', True))
pow_difficulty = os.getenv('POW_DIFFICULTY', '000032')
retry_times = int(os.getenv('RETRY_TIMES', 3))
conversation_only = is_true(os.getenv('CONVERSATION_ONLY', False))
enable_limit = is_true(os.getenv('ENABLE_LIMIT', True))
upload_by_url = is_true(os.getenv('UPLOAD_BY_URL', False))
check_model = is_true(os.getenv('CHECK_MODEL', False))
scheduled_refresh = is_true(os.getenv('SCHEDULED_REFRESH', False))
random_token = is_true(os.getenv('RANDOM_TOKEN', True))
oai_language = os.getenv('OAI_LANGUAGE', 'en-US')
chat_requirements_timeout = int(os.getenv('CHAT_REQUIREMENTS_TIMEOUT', 15))
chat_request_timeout = int(os.getenv('CHAT_REQUEST_TIMEOUT', 30))
accept_language = os.getenv('ACCEPT_LANGUAGE', 'en-US,en;q=0.9')
client_timezone = os.getenv('CLIENT_TIMEZONE', 'America/Los_Angeles')
client_timezone_offset_min = int(os.getenv('CLIENT_TIMEZONE_OFFSET_MIN', -480))

authorization_list = authorization.split(',') if authorization else []
chatgpt_base_url_list = chatgpt_base_url.split(',') if chatgpt_base_url else []
ark0se_token_url_list = ark0se_token_url.split(',') if ark0se_token_url else []
proxy_url_list = proxy_url.split(',') if proxy_url else []
sentinel_proxy_url_list = sentinel_proxy_url.split(',') if sentinel_proxy_url else []
impersonate_list = ast.literal_eval(impersonate_list_str)
user_agents_list = ast.literal_eval(user_agents_list_str)
device_tuple = ast.literal_eval(device_tuple_str)
browser_tuple = ast.literal_eval(browser_tuple_str)
platform_tuple = ast.literal_eval(platform_tuple_str)

enable_gateway = is_true(os.getenv('ENABLE_GATEWAY', False))
auto_seed = is_true(os.getenv('AUTO_SEED', True))
force_no_history = is_true(os.getenv('FORCE_NO_HISTORY', False))
no_sentinel = is_true(os.getenv('NO_SENTINEL', False))
init_tokens = os.getenv('INIT_TOKENS', '')
init_proxies = os.getenv('INIT_PROXIES', '')
init_group_size = int(os.getenv('INIT_GROUP_SIZE', 25))
init_apply_on_empty = is_true(os.getenv('INIT_APPLY_ON_EMPTY', True))
init_force = is_true(os.getenv('INIT_FORCE', False))

# ========================= OpenAI 前端版本指纹（反降智） =========================
# 这两个值需要定期（1-2 周）从 chatgpt.com 的真实请求中刷新，否则会被风控识别
# 抓取方法：浏览器登录 chatgpt.com → F12 Network → 任一 /backend-api/* 请求 → Headers
oai_client_version = os.getenv(
    'OAI_CLIENT_VERSION',
    'prod-767c16cfce2fbcbdd1ae079fcf0b43838ff1b3ed',
)
oai_client_build_number = os.getenv(
    'OAI_CLIENT_BUILD_NUMBER',
    '6549031',
)

# ========================= OpenAI Auth0 凭据刷新 =========================
# 默认 Codex CLI client_id（新版 OpenAI 登录流程，适用于 auth.openai.com 端点）
# 老版 iOS app client_id `pdlLIX2Y72MIl2rhLhTE9VV9bN905kBh` + auth0.openai.com 已失效（返回 404）
openai_auth_client_id = os.getenv(
    'OPENAI_AUTH_CLIENT_ID',
    'app_EMoamEEZ73f0CkXaXp7hrann',
)
# 默认 localhost HTTP 回调（Codex CLI 风格，浏览器能正常识别）
openai_auth_redirect_uri = os.getenv(
    'OPENAI_AUTH_REDIRECT_URI',
    'http://localhost:1455/auth/callback',
)
# 新版 Authorize / Token 端点（去掉了 0）
openai_auth_authorize_url = os.getenv(
    'OPENAI_AUTH_AUTHORIZE_URL',
    'https://auth.openai.com/oauth/authorize',
)
openai_auth_token_url = os.getenv(
    'OPENAI_AUTH_TOKEN_URL',
    'https://auth.openai.com/oauth/token',
)
openai_auth_scope = os.getenv(
    'OPENAI_AUTH_SCOPE',
    'openid profile email offline_access',
)

# ========================= Antiban (风控规避层) =========================
# 总开关；默认关闭，保持向后兼容
enable_antiban = is_true(os.getenv('ENABLE_ANTIBAN', False))
# IP 粘性桶：每个代理最多容纳的账号数
bucket_max_accounts_per_ip = int(os.getenv('BUCKET_MAX_ACCOUNTS_PER_IP', 5))
# 严格 IP 绑定：开启后账号一旦绑定 IP 即永不漂移
strict_ip_binding = is_true(os.getenv('STRICT_IP_BINDING', True))
# 账号级最小请求间隔秒数（Team/Plus 默认 60s）
account_min_interval_seconds = int(os.getenv('ACCOUNT_MIN_INTERVAL_SECONDS', 60))
# 免费账号最小请求间隔秒数（通常需更长）
free_account_min_interval_seconds = int(os.getenv('FREE_ACCOUNT_MIN_INTERVAL_SECONDS', 180))
# 冷却抖动比例（±jitter）
account_cooldown_jitter = float(os.getenv('ACCOUNT_COOLDOWN_JITTER', 0.3))
# 账号排队最长等待秒数；超过则返回 503 让上游切换
account_max_wait_seconds = int(os.getenv('ACCOUNT_MAX_WAIT_SECONDS', 30))
# Geo 查询服务提供商：ip-api | ipinfo
ip_geo_provider = os.getenv('IP_GEO_PROVIDER', 'ip-api')
# Geo 缓存 TTL（天）
ip_geo_cache_ttl_days = int(os.getenv('IP_GEO_CACHE_TTL_DAYS', 30))
# 熔断参数
circuit_429_cooldown = int(os.getenv('CIRCUIT_429_COOLDOWN', 1800))
circuit_403_cooldown = int(os.getenv('CIRCUIT_403_COOLDOWN', 3600))
circuit_dead_account_recheck_hours = int(os.getenv('CIRCUIT_DEAD_ACCOUNT_RECHECK_HOURS', 24))
circuit_bucket_heal_minutes = int(os.getenv('CIRCUIT_BUCKET_HEAL_MINUTES', 30))

# ========================= Session Sticky (LibreChat 会话粘性) =========================
# 用于 LibreChat → New-API → chat2api 链路；将 LibreChat 端 conversationId
# 翻译为 ChatGPT 服务端 conversation_id，实现窗口级会话连续。默认关闭。
enable_session_sticky = is_true(os.getenv('ENABLE_SESSION_STICKY', False))
# SQLite 文件路径（默认在 data 卷内，跟随实例数据；与 utils/globals.DATA_FOLDER 保持一致）
session_db_path = os.getenv('SESSION_DB_PATH', os.path.join('data', 'sessions.db'))
# 多少天未更新的映射会被清理（cleanup_expired 调用时生效）
session_ttl_days = int(os.getenv('SESSION_TTL_DAYS', 30))
# request body 中携带 LibreChat conversationId 的字段名（默认与 librechat.yaml addParams 对齐）
session_lc_field = os.getenv('SESSION_LC_FIELD', 'librechat_conversation_id')
# 命中映射时是否把 messages[] 截短到最后一条 user message（依赖 ChatGPT 服务端续接历史，省 token）
session_trim_to_last_user = is_true(os.getenv('SESSION_TRIM_TO_LAST_USER', True))

with open('version.txt') as f:
    version = f.read().strip()

logger.info("-" * 60)
logger.info(f"Chat2Api {version} | https://github.com/lanqian528/chat2api")
logger.info("-" * 60)
logger.info("Environment variables:")
logger.info("------------------------- Security -------------------------")
logger.info("API_PREFIX:        " + str(api_prefix))
logger.info("AUTHORIZATION:     " + str(authorization_list))
logger.info("ADMIN_PASSWORD:    " + str(bool(admin_password)))
logger.info("ADMIN_IP_WHITELIST:" + (f" {len(admin_ip_whitelist)} rule(s) [{'trust_proxy' if admin_trust_proxy else 'no_proxy'}]" if admin_ip_whitelist else " (disabled)"))
logger.info("AUTH_KEY:          " + str(auth_key))
logger.info("------------------------- Request --------------------------")
logger.info("CHATGPT_BASE_URL:  " + str(chatgpt_base_url_list))
logger.info("PROXY_URL:         " + str(proxy_url_list))
logger.info("EXPORT_PROXY_URL:  " + str(export_proxy_url))
logger.info("FILE_HOST:     " + str(file_host))
logger.info("VOICE_HOST:    " + str(voice_host))
logger.info("IMPERSONATE:       " + str(impersonate_list))
logger.info("USER_AGENTS:       " + str(user_agents_list))
logger.info("---------------------- Functionality -----------------------")
logger.info("HISTORY_DISABLED:  " + str(history_disabled))
logger.info("POW_DIFFICULTY:    " + str(pow_difficulty))
logger.info("RETRY_TIMES:       " + str(retry_times))
logger.info("CONVERSATION_ONLY: " + str(conversation_only))
logger.info("ENABLE_LIMIT:      " + str(enable_limit))
logger.info("UPLOAD_BY_URL:     " + str(upload_by_url))
logger.info("CHECK_MODEL:       " + str(check_model))
logger.info("SCHEDULED_REFRESH: " + str(scheduled_refresh))
logger.info("RANDOM_TOKEN:      " + str(random_token))
logger.info("OAI_LANGUAGE:      " + str(oai_language))
logger.info("ACCEPT_LANGUAGE:   " + str(accept_language))
logger.info("CLIENT_TIMEZONE:   " + str(client_timezone))
logger.info("CLIENT_TZ_OFFSET:  " + str(client_timezone_offset_min))
logger.info("CHAT_REQUIREMENTS_TIMEOUT: " + str(chat_requirements_timeout))
logger.info("CHAT_REQUEST_TIMEOUT:      " + str(chat_request_timeout))
logger.info("OAI_CLIENT_VERSION:        " + str(oai_client_version))
logger.info("OAI_CLIENT_BUILD_NUMBER:   " + str(oai_client_build_number))
logger.info("------------------------- Gateway --------------------------")
logger.info("ENABLE_GATEWAY:    " + str(enable_gateway))
logger.info("AUTO_SEED:         " + str(auto_seed))
logger.info("FORCE_NO_HISTORY: " + str(force_no_history))
logger.info("INIT_TOKENS:       " + str(bool(init_tokens)))
logger.info("INIT_PROXIES:      " + str(bool(init_proxies)))
logger.info("INIT_GROUP_SIZE:   " + str(init_group_size))
logger.info("INIT_FORCE:        " + str(init_force))
logger.info("------------------------- Antiban --------------------------")
logger.info("ENABLE_ANTIBAN:    " + str(enable_antiban))
logger.info("STRICT_IP_BINDING: " + str(strict_ip_binding))
logger.info("BUCKET_MAX_ACCOUNTS_PER_IP: " + str(bucket_max_accounts_per_ip))
logger.info("ACCOUNT_MIN_INTERVAL_SECONDS: " + str(account_min_interval_seconds))
logger.info("ACCOUNT_MAX_WAIT_SECONDS:     " + str(account_max_wait_seconds))
logger.info("IP_GEO_PROVIDER:   " + str(ip_geo_provider))
logger.info("CIRCUIT_429_COOLDOWN: " + str(circuit_429_cooldown))
logger.info("CIRCUIT_403_COOLDOWN: " + str(circuit_403_cooldown))
logger.info("--------------------- Session Sticky -----------------------")
logger.info("ENABLE_SESSION_STICKY: " + str(enable_session_sticky))
if enable_session_sticky:
    logger.info("SESSION_DB_PATH:       " + str(session_db_path))
    logger.info("SESSION_TTL_DAYS:      " + str(session_ttl_days))
    logger.info("SESSION_LC_FIELD:      " + str(session_lc_field))
    logger.info("SESSION_TRIM_TO_LAST_USER: " + str(session_trim_to_last_user))
logger.info("-" * 60)
