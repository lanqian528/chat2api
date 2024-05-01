import base64
import hashlib
import json
import random
import time
from datetime import datetime, timedelta, timezone

answers = {}
cores = [8, 12, 16, 24, 32]
screens = [3000, 4000, 6000]
timeLayout = "%a %b %d %Y %H:%M:%S"


def get_parse_time():
    now = datetime.now(timezone(timedelta(hours=-8)))
    return now.strftime(timeLayout) + " GMT-0800 (Pacific Time)"


def get_config(user_agent):
    random.seed(int(time.time() * 1e9))
    core = random.choice(cores)
    screen = random.choice(screens)
    config = [core + screen, get_parse_time(), 4294705152, 0, user_agent]
    config += [
        "https://cdn.oaistatic.com/_next/static/chunks/pages/_app-6179027f2701f350.js?dpl=61795df7b34494cdf55bd45e3973183b0a174e5b",
        "dpl=61795df7b34494cdf55bd45e3973183b0a174e5b",
    ]
    config += ["en-US", "en-US,en"]
    return config


def calc_proof_token(seed, diff, config):
    diff_len = len(diff) // 2
    for i in range(1000000):
        config[3] = i
        json_data = json.dumps(config, separators=(',', ':'), ensure_ascii=False)
        base = base64.b64encode(json_data.encode()).decode()
        hasher = hashlib.sha3_512()
        hasher.update((seed + base).encode())
        hash_value = hasher.digest()

        if hash_value[:diff_len].hex() <= diff:
            result = "gAAAAAB" + base
            return result

    return "gAAAAABwQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D" + base64.b64encode(f'"{seed}"'.encode()).decode()


def chat_requirements_body(config):
    json_data = json.dumps(config).encode()
    base = base64.b64encode(json_data).decode()
    retObj = {'p': 'gAAAAAC' + base}
    return retObj
