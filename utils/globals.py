import json
import os

import utils.configs as configs
from utils.Logger import logger

DATA_FOLDER = "data"
TOKENS_FILE = os.path.join(DATA_FOLDER, "token.txt")
REFRESH_MAP_FILE = os.path.join(DATA_FOLDER, "refresh_map.json")
ERROR_TOKENS_FILE = os.path.join(DATA_FOLDER, "error_token.txt")
WSS_MAP_FILE = os.path.join(DATA_FOLDER, "wss_map.json")
FP_FILE = os.path.join(DATA_FOLDER, "fp_map.json")
ROUTING_CONFIG_FILE = os.path.join(DATA_FOLDER, "routing_config.json")
SEED_MAP_FILE = os.path.join(DATA_FOLDER, "seed_map.json")
CONVERSATION_MAP_FILE = os.path.join(DATA_FOLDER, "conversation_map.json")
# Antiban 持久化文件（PR-1 骨架）
ANTIBAN_BUCKET_FILE = os.path.join(DATA_FOLDER, "antiban_bucket.json")
ANTIBAN_GEO_FILE = os.path.join(DATA_FOLDER, "antiban_geo.json")
ANTIBAN_DEAD_FILE = os.path.join(DATA_FOLDER, "antiban_dead.json")
# 账号风险嗅探：仅记录命中的软警告，不立即标 dead（Step A：观察期，校准关键词）
ACCOUNT_WARNINGS_FILE = os.path.join(DATA_FOLDER, "account_warnings.json")
# Harvester 账号元数据（不含密码，仅 email+note+proxy_name+采集历史）
HARVESTER_ACCOUNTS_FILE = os.path.join(DATA_FOLDER, "harvester_accounts.json")

count = 0
token_list = []
error_token_list = []
refresh_map = {}
wss_map = {}
fp_map = {}
routing_config = {}
seed_map = {}
conversation_map = {}
# Antiban 内存状态（PR-1 骨架，后续 PR 填充）
antiban_bucket = {"buckets": {}, "account_index": {}}
antiban_geo_cache = {}
antiban_dead_tokens = {}
# 账号风险嗅探：token -> [{hit_at, snippet, pattern, conversation_id}, ...]
account_warnings = {}
impersonate_list = [
    "chrome119",
    "chrome120",
    "chrome123",
] if not configs.impersonate_list else configs.impersonate_list

if not os.path.exists(DATA_FOLDER):
    os.makedirs(DATA_FOLDER)

if os.path.exists(REFRESH_MAP_FILE):
    with open(REFRESH_MAP_FILE, "r") as f:
        try:
            refresh_map = json.load(f)
        except:
            refresh_map = {}
else:
    refresh_map = {}

if os.path.exists(WSS_MAP_FILE):
    with open(WSS_MAP_FILE, "r") as f:
        try:
            wss_map = json.load(f)
        except:
            wss_map = {}
else:
    wss_map = {}

if os.path.exists(FP_FILE):
    with open(FP_FILE, "r", encoding="utf-8") as f:
        try:
            fp_map = json.load(f)
        except:
            fp_map = {}
else:
    fp_map = {}

if os.path.exists(ROUTING_CONFIG_FILE):
    with open(ROUTING_CONFIG_FILE, "r", encoding="utf-8") as f:
        try:
            routing_config = json.load(f)
        except:
            routing_config = {}
else:
    routing_config = {}

if os.path.exists(SEED_MAP_FILE):
    with open(SEED_MAP_FILE, "r") as f:
        try:
            seed_map = json.load(f)
        except:
            seed_map = {}
else:
    seed_map = {}

if os.path.exists(CONVERSATION_MAP_FILE):
    with open(CONVERSATION_MAP_FILE, "r") as f:
        try:
            conversation_map = json.load(f)
        except:
            conversation_map = {}
else:
    conversation_map = {}

# Antiban 冷启动加载（骨架：无数据时保持默认空结构）
if os.path.exists(ANTIBAN_BUCKET_FILE):
    with open(ANTIBAN_BUCKET_FILE, "r", encoding="utf-8") as f:
        try:
            antiban_bucket = json.load(f)
            antiban_bucket.setdefault("buckets", {})
            antiban_bucket.setdefault("account_index", {})
        except:
            antiban_bucket = {"buckets": {}, "account_index": {}}

if os.path.exists(ANTIBAN_GEO_FILE):
    with open(ANTIBAN_GEO_FILE, "r", encoding="utf-8") as f:
        try:
            antiban_geo_cache = json.load(f)
        except:
            antiban_geo_cache = {}

if os.path.exists(ANTIBAN_DEAD_FILE):
    with open(ANTIBAN_DEAD_FILE, "r", encoding="utf-8") as f:
        try:
            antiban_dead_tokens = json.load(f)
        except:
            antiban_dead_tokens = {}

if os.path.exists(ACCOUNT_WARNINGS_FILE):
    with open(ACCOUNT_WARNINGS_FILE, "r", encoding="utf-8") as f:
        try:
            account_warnings = json.load(f)
        except:
            account_warnings = {}

if os.path.exists(TOKENS_FILE):
    with open(TOKENS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                token_list.append(line.strip())
else:
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        pass

if os.path.exists(ERROR_TOKENS_FILE):
    with open(ERROR_TOKENS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                error_token_list.append(line.strip())
else:
    with open(ERROR_TOKENS_FILE, "w", encoding="utf-8") as f:
        pass

if token_list:
    logger.info(f"Token list count: {len(token_list)}, Error token list count: {len(error_token_list)}")
    logger.info("-" * 60)


def persist_token_list():
    """全量重写 data/token.txt（用于 cookie 滚动续期后同步磁盘）。"""
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        for t in token_list:
            f.write(t + "\n")


def persist_fp_map():
    """全量重写 data/fp_map.json。"""
    with open(FP_FILE, "w", encoding="utf-8") as f:
        json.dump(fp_map, f, indent=2, ensure_ascii=False)
