import hashlib
import json
import random
import time

import jwt
from fastapi import Request, HTTPException, Security
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials

import utils.globals as globals
from app import app, security_scheme
from chatgpt.authorization import verify_token
from chatgpt.fp import get_fp
from gateway.reverseProxy import get_real_req_token
from utils.Client import Client
from utils.Logger import logger
from utils.configs import proxy_url_list, chatgpt_base_url_list, authorization_list, accept_language, oai_language
from utils.routing import get_bound_proxy

base_headers = {
    'accept': '*/*',
    'accept-encoding': 'gzip, deflate, br, zstd',
    'accept-language': accept_language,
    'content-type': 'application/json',
    'oai-language': oai_language,
    'priority': 'u=1, i',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
}


def verify_authorization(bearer_token):
    if not bearer_token:
        raise HTTPException(status_code=401, detail="Authorization header is missing")
    if bearer_token not in authorization_list:
        raise HTTPException(status_code=401, detail="Invalid authorization")


@app.get("/seedtoken")
async def get_seedtoken(request: Request, credentials: HTTPAuthorizationCredentials = Security(security_scheme)):
    verify_authorization(credentials.credentials)
    try:
        params = request.query_params
        seed = params.get("seed")

        if seed:
            if seed not in globals.seed_map:
                raise HTTPException(status_code=404, detail=f"Seed '{seed}' not found")
            return {
                "status": "success",
                "data": {
                    "seed": seed,
                    "token": globals.seed_map[seed]["token"]
                }
            }

        token_map = {
            seed: data["token"]
            for seed, data in globals.seed_map.items()
        }
        return {"status": "success", "data": token_map}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.post("/seedtoken")
async def set_seedtoken(request: Request, credentials: HTTPAuthorizationCredentials = Security(security_scheme)):
    verify_authorization(credentials.credentials)
    data = await request.json()

    seed = data.get("seed")
    token = data.get("token")

    if seed not in globals.seed_map:
        globals.seed_map[seed] = {
            "token": token,
            "conversations": []
        }
    else:
        globals.seed_map[seed]["token"] = token

    with open(globals.SEED_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(globals.seed_map, f, indent=4)

    return {"status": "success", "message": "Token updated successfully"}


@app.delete("/seedtoken")
async def delete_seedtoken(request: Request, credentials: HTTPAuthorizationCredentials = Security(security_scheme)):
    verify_authorization(credentials.credentials)

    try:
        data = await request.json()
        seed = data.get("seed")

        if seed == "clear":
            globals.seed_map.clear()
            with open(globals.SEED_MAP_FILE, "w", encoding="utf-8") as f:
                json.dump(globals.seed_map, f, indent=4)
            return {"status": "success", "message": "All seeds deleted successfully"}

        if not seed:
            raise HTTPException(status_code=400, detail="Missing required field: seed")

        if seed not in globals.seed_map:
            raise HTTPException(status_code=404, detail=f"Seed '{seed}' not found")
        del globals.seed_map[seed]

        with open(globals.SEED_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(globals.seed_map, f, indent=4)

        return {
            "status": "success",
            "message": f"Seed '{seed}' deleted successfully"
        }

    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON data")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


async def chatgpt_account_check(access_token):
    auth_info = {}
    client = Client(proxy=random.choice(proxy_url_list) if proxy_url_list else None)
    try:
        host_url = random.choice(chatgpt_base_url_list) if chatgpt_base_url_list else "https://chatgpt.com"
        req_token = await get_real_req_token(access_token)
        access_token = await verify_token(req_token)
        fp = get_fp(req_token).copy()
        proxy_url = fp.pop("proxy_url", None)
        impersonate = fp.pop("impersonate", "safari15_3")

        headers = base_headers.copy()
        headers.update(fp)
        headers.update({"authorization": f"Bearer {access_token}"})

        session_id = hashlib.md5(access_token.encode()).hexdigest()
        proxy_url = proxy_url.replace("{}", session_id) if proxy_url else None
        client = Client(proxy=proxy_url, impersonate=impersonate)
        r = await client.get(f"{host_url}/backend-api/models?history_and_training_disabled=false", headers=headers,
                             timeout=10)
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        models = r.json()
        r = await client.get(f"{host_url}/backend-api/accounts/check/v4-2023-04-27", headers=headers, timeout=10)
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        accounts_info = r.json()

        auth_info.update({"models": models["models"]})
        auth_info.update({"accounts_info": accounts_info})

        account_ordering = accounts_info.get("account_ordering", [])
        is_deactivated = True
        plan_type = None
        team_ids = []
        for account in account_ordering:
            this_is_deactivated = accounts_info['accounts'].get(account, {}).get("account", {}).get("is_deactivated", False)
            this_plan_type = accounts_info['accounts'].get(account, {}).get("account", {}).get("plan_type", "free")

            if not this_is_deactivated:
                is_deactivated = False

            if "team" in this_plan_type and not this_is_deactivated:
                plan_type = this_plan_type
                team_ids.append(account)
            elif plan_type is None:
                plan_type = this_plan_type

        auth_info.update({"accountCheckInfo": {
            "is_deactivated": is_deactivated,
            "plan_type": plan_type,
            "team_ids": team_ids
        }})

        return auth_info
    except Exception as e:
        logger.error(f"chatgpt_account_check: {e}")
        return {}
    finally:
        await client.close()


async def chatgpt_refresh(refresh_token):
    session_id = hashlib.md5(refresh_token.encode()).hexdigest()
    bound_proxy = get_bound_proxy(refresh_token)
    proxy_url = bound_proxy or (random.choice(proxy_url_list).replace("{}", session_id) if proxy_url_list else None)
    if proxy_url:
        proxy_url = proxy_url.replace("{}", session_id)
    client = Client(proxy=proxy_url)
    try:
        data = {
            "client_id": "pdlLIX2Y72MIl2rhLhTE9VV9bN905kBh",
            "grant_type": "refresh_token",
            "redirect_uri": "com.openai.chat://auth0.openai.com/ios/com.openai.chat/callback",
            "refresh_token": refresh_token
        }
        r = await client.post("https://auth0.openai.com/oauth/token", json=data, timeout=10)
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        res = r.json()
        auth_info = {}
        auth_info.update(res)
        auth_info.update({"refresh_token": refresh_token})
        auth_info.update({"accessToken": res.get("access_token", "")})
        return auth_info
    except Exception as e:
        logger.error(f"chatgpt_refresh: {e}")
        return {}
    finally:
        await client.close()


@app.post("/auth/refresh")
async def refresh(request: Request):
    auth_info = {}
    form_data = await request.form()

    auth_info.update(form_data)

    access_token = auth_info.get("access_token", auth_info.get("accessToken", ""))
    refresh_token = auth_info.get("refresh_token", "")

    if not refresh_token and not access_token:
        raise HTTPException(status_code=401, detail="refresh_token or access_token is required")

    need_refresh = True
    if access_token:
        try:
            access_token_info = jwt.decode(access_token, options={"verify_signature": False})
            exp = access_token_info.get("exp", 0)
            if exp > int(time.time()) + 60 * 60 * 24 * 5:
                need_refresh = False
        except Exception as e:
            logger.error(f"access_token: {e}")

    if refresh_token and need_refresh:
        chatgpt_refresh_info = await chatgpt_refresh(refresh_token)
        if chatgpt_refresh_info:
            auth_info.update(chatgpt_refresh_info)
            access_token = auth_info.get("accessToken", "")
            account_check_info = await chatgpt_account_check(access_token)
            if account_check_info:
                auth_info.update(account_check_info)
                auth_info.update({"accessToken": access_token})
                return Response(content=json.dumps(auth_info), media_type="application/json")
    elif access_token:
        account_check_info = await chatgpt_account_check(access_token)
        if account_check_info:
            auth_info.update(account_check_info)
            auth_info.update({"accessToken": access_token})
            return Response(content=json.dumps(auth_info), media_type="application/json")

    raise HTTPException(status_code=401, detail="Unauthorized")
