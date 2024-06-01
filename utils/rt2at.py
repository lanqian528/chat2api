import os
import random
import threading
import time

from curl_cffi import requests
from utils.Logger import logger
import schedule

# REFRESH_TOKEN_FILE = "./data/refresh_token.txt"

def start_refresh_token(REFRESH_TOKEN_FILE,ACCESS_TOKEN_FILE):
    logger.info("start refresh tokens...")
    refresh_tokens = []
    acc_tokens = []
    with open(REFRESH_TOKEN_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                refresh_tokens.append(line.strip())
    for i in refresh_tokens:
        token = get_access_token(i)
        time.sleep(random.random())
        if token:
            acc_tokens.append(token)
        else:
            logger.error(f"Failed to get access token from refresh token: {i}")

    with open(ACCESS_TOKEN_FILE, "w", encoding="utf-8") as f:
        for i in acc_tokens:
            f.write(i + "\n")

def get_access_token(refresh_token):
    try:
        url = "https://token.oaifree.com/api/auth/refresh"

        headers = {
            'Accept': '*/*',
            'Connection': 'keep-alive',
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        data = {
            "refresh_token": refresh_token
        }
        response = requests.post(url=url,
                                 impersonate=random.choice(["chrome", "safari", "safari_ios"]), headers=headers,
                                 data=data)

        access_token = response.json().get("access_token")
    except Exception as e:
        access_token = None

    return access_token
        
def load_tokens(token_list,ACCESS_TOKEN_FILE):
    token_list.clear()
    if os.path.exists(ACCESS_TOKEN_FILE):
        with open(ACCESS_TOKEN_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip() and not line.startswith("#"):
                    token_list.append(line.strip())
    else:
        with open(ACCESS_TOKEN_FILE, "w", encoding="utf-8") as f:
            pass

    if token_list:
        logger.info(f"Token list count: {len(token_list)}")

   
def start_refresh_sheduler(token_list,REFRESH_TOKEN_FILE,ACCESS_TOKEN_FILE):
    def run_scheduler():
        # 开启任务后，立即执行一次刷新
        start_refresh_token(REFRESH_TOKEN_FILE,ACCESS_TOKEN_FILE)
        load_tokens(token_list,ACCESS_TOKEN_FILE)
        while True:
            schedule.run_pending()
            time.sleep(1)
    # 设置定时任务，每天凌晨04.00刷新token
    schedule.every().day.at("04:00").do(start_refresh_token,REFRESH_TOKEN_FILE,ACCESS_TOKEN_FILE)
    # 设置定时任务，每天凌晨05.00读取token
    schedule.every().day.at("05:00").do(load_tokens,token_list,ACCESS_TOKEN_FILE)
    # 也可以改为每9天刷新一次
    # schedule.every(9).days.at("04:00").do(read_refresh_token,RT_FILE,TOKENS_FILE)
    # schedule.every(9).days.at("05:00").do(load_tokens)
    threading.Thread(target=run_scheduler, daemon=True).start()


if __name__ == '__main__':
    REFRESH_TOKEN_FILE = "./data/refresh_token.txt"
    ACCESS_TOKEN_FILE = "./data/token.txt"
    token_list = []
    start_refresh_sheduler(token_list,REFRESH_TOKEN_FILE,ACCESS_TOKEN_FILE)
    while True:
        time.sleep(1)
        pass