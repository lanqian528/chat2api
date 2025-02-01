from fastapi import Request

import utils.globals as globals
from utils.configs import proxy_url_list
from app import app
from utils import generate_md5, cache
from utils.configs import api_prefix


def get_cf_cookie(user_agent, proxy_url=""):
    hash_id = generate_md5(f'{proxy_url}-{user_agent}')
    key = f"cf-cookie:{hash_id}"
    return cache.get(key)


@app.post(f"/{api_prefix}/api/set-cf-cookie" if api_prefix else "/api/set-cf-cookie")
async def set_cf_cookie(request: Request):
    req_data = await request.json()
    hash_id = generate_md5(f'{req_data["proxy_url"]}-{req_data["user_agent"]}')
    key = f"cf-cookie:{hash_id}"
    cache.set(key, req_data, 3600 * 24)


@app.get(f"/{api_prefix}/api/get-cf-list" if api_prefix else "/api/get-cf-list")
async def get_cf_list(request: Request):
    user_agent_list = [i["user-agent"] for i in globals.fp_map.values()]
    proxy_url_pool = proxy_url_list + [""]
    result = {
        "exist_data_list": [],
        "need_update": {
            "proxy_url_pool": proxy_url_pool,
            "user_agent_list": list(set(user_agent_list))
        },
    }

    for proxy_url in proxy_url_pool:
        for user_agent in user_agent_list:
            cf_cookie = get_cf_cookie(user_agent, proxy_url)
            if cf_cookie:
                result["exist_data_list"].append(cf_cookie)

    return result
