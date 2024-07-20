import pybase64
import json
import random
import time
from typing import Any, Callable, Dict, List, Union


class OrderedMap:
    def __init__(self):
        self.keys = []
        self.values = {}

    def add(self, key: str, value: Any):
        if key not in self.values:
            self.keys.append(key)
        self.values[key] = value

    def to_json(self):
        return json.dumps({k: self.values[k] for k in self.keys})


TurnTokenList = List[List[Any]]
FloatMap = Dict[float, Any]
StringMap = Dict[str, Any]
FuncType = Callable[..., Any]


def get_turnstile_token(dx: str, p: str) -> Union[str, None]:
    try:
        decoded_bytes = pybase64.b64decode(dx)
        return process_turnstile_token(decoded_bytes.decode(), p)
    except Exception as e:
        print(f"Error in get_turnstile_token: {e}")
        return None


def process_turnstile_token(dx: str, p: str) -> str:
    result = []
    p_length = len(p)
    if p_length != 0:
        for i, r in enumerate(dx):
            result.append(chr(ord(r) ^ ord(p[i % p_length])))
    else:
        result = list(dx)
    return ''.join(result)


def is_slice(input_val: Any) -> bool:
    return isinstance(input_val, (list, tuple))


def is_float(input_val: Any) -> bool:
    return isinstance(input_val, float)


def is_string(input_val: Any) -> bool:
    return isinstance(input_val, str)


def to_str(input_val: Any) -> str:
    if input_val is None:
        return "undefined"
    elif is_float(input_val):
        return str(input_val)
    elif is_string(input_val):
        special_cases = {
            "window.Math": "[object Math]",
            "window.Reflect": "[object Reflect]",
            "window.performance": "[object Performance]",
            "window.localStorage": "[object Storage]",
            "window.Object": "function Object() { [native code] }",
            "window.Reflect.set": "function set() { [native code] }",
            "window.performance.now": "function () { [native code] }",
            "window.Object.create": "function create() { [native code] }",
            "window.Object.keys": "function keys() { [native code] }",
            "window.Math.random": "function random() { [native code] }"
        }
        return special_cases.get(input_val, input_val)
    elif isinstance(input_val, list) and all(isinstance(item, str) for item in input_val):
        return ','.join(input_val)
    else:
        return str(input_val)


def get_func_map() -> FloatMap:
    process_map: FloatMap = {}

    def func_1(e: float, t: float):
        e_str = to_str(process_map[e])
        t_str = to_str(process_map[t])
        res = process_turnstile_token(e_str, t_str)
        process_map[e] = res

    def func_2(e: float, t: Any):
        process_map[e] = t

    def func_5(e: float, t: float):
        n = process_map[e]
        tres = process_map[t]
        if is_slice(n):
            nt = n + [tres]
            process_map[e] = nt
        else:
            if is_string(n) or is_string(tres):
                res = to_str(n) + to_str(tres)
            elif is_float(n) and is_float(tres):
                res = n + tres
            else:
                res = "NaN"
            process_map[e] = res

    def func_6(e: float, t: float, n: float):
        tv = process_map[t]
        nv = process_map[n]
        if is_string(tv) and is_string(nv):
            res = f"{tv}.{nv}"
            if res == "window.document.location":
                process_map[e] = "https://chatgpt.com/"
            else:
                process_map[e] = res
        else:
            print("func type 6 error")

    def func_24(e: float, t: float, n: float):
        tv = process_map[t]
        nv = process_map[n]
        if is_string(tv) and is_string(nv):
            process_map[e] = f"{tv}.{nv}"
        else:
            print("func type 24 error")

    def func_7(e: float, *args):
        n = [process_map[arg] for arg in args]
        ev = process_map[e]
        if isinstance(ev, str):
            if ev == "window.Reflect.set":
                obj = n[0]
                key_str = str(n[1])
                val = n[2]
                obj.add(key_str, val)
        elif callable(ev):
            ev(*n)

    def func_17(e: float, t: float, *args):
        i = [process_map[arg] for arg in args]
        tv = process_map[t]
        res = None
        if isinstance(tv, str):
            if tv == "window.performance.now":
                current_time = time.time_ns()
                elapsed_ns = current_time - int(start_time * 1e9)
                res = (elapsed_ns + random.random()) / 1e6
            elif tv == "window.Object.create":
                res = OrderedMap()
            elif tv == "window.Object.keys":
                if isinstance(i[0], str) and i[0] == "window.localStorage":
                    res = ["STATSIG_LOCAL_STORAGE_INTERNAL_STORE_V4", "STATSIG_LOCAL_STORAGE_STABLE_ID",
                           "client-correlated-secret", "oai/apps/capExpiresAt", "oai-did",
                           "STATSIG_LOCAL_STORAGE_LOGGING_REQUEST", "UiState.isNavigationCollapsed.1"]
            elif tv == "window.Math.random":
                res = random.random()
        elif callable(tv):
            res = tv(*i)
        process_map[e] = res

    def func_8(e: float, t: float):
        process_map[e] = process_map[t]

    def func_14(e: float, t: float):
        tv = process_map[t]
        if is_string(tv):
            token_list = json.loads(tv)
            process_map[e] = token_list
        else:
            print("func type 14 error")

    def func_15(e: float, t: float):
        tv = process_map[t]
        process_map[e] = json.dumps(tv)

    def func_18(e: float):
        ev = process_map[e]
        e_str = to_str(ev)
        decoded = pybase64.b64decode(e_str).decode()
        process_map[e] = decoded

    def func_19(e: float):
        ev = process_map[e]
        e_str = to_str(ev)
        encoded = pybase64.b64encode(e_str.encode()).decode()
        process_map[e] = encoded

    def func_20(e: float, t: float, n: float, *args):
        o = [process_map[arg] for arg in args]
        ev = process_map[e]
        tv = process_map[t]
        if ev == tv:
            nv = process_map[n]
            if callable(nv):
                nv(*o)
            else:
                print("func type 20 error")

    def func_21(*args):
        pass

    def func_23(e: float, t: float, *args):
        i = list(args)
        ev = process_map[e]
        tv = process_map[t]
        if ev is not None:
            if callable(tv):
                tv(*i)

    process_map.update({
        1: func_1, 2: func_2, 5: func_5, 6: func_6, 24: func_24, 7: func_7,
        17: func_17, 8: func_8, 10: "window", 14: func_14, 15: func_15,
        18: func_18, 19: func_19, 20: func_20, 21: func_21, 23: func_23
    })

    return process_map

start_time = 0


def process_turnstile(dx: str, p: str) -> str:
    global start_time
    start_time = time.time()
    tokens = get_turnstile_token(dx, p)
    if tokens is None:
        return ""

    token_list = json.loads(tokens)
    # print(token_list)
    res = ""
    process_map = get_func_map()

    def func_3(e: str):
        nonlocal res
        res = pybase64.b64encode(e.encode()).decode()

    process_map[3] = func_3
    process_map[9] = token_list
    process_map[16] = p

    for token in token_list:
        try:
            e = token[0]
            t = token[1:]
            f = process_map.get(e)
            if callable(f):
                f(*t)
            else:
                pass
                # print(f"Warning: No function found for key {e}")
        except Exception as exc:
            pass
            # print(f"Error processing token {token}: {exc}")

    return res


if __name__ == "__main__":
    result = process_turnstile(
        "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OT0jEFwMC1UPPyMwATQnO1oxHz8DNSIoAScYMBMtDi8iFgwgHwwKMAxnDjsXDQooCx4YHSY4JQYYPgQ0Cz0PVkQEEQYqKCIWPTELLBsxElgUMBcENhMKPQQRbyQVRhJdREdUW0tUYB4MX2BjeAU8bxEfZUVYW1VHTF5OSQV/f1xBMU5Jamd7QX9fbWd4H3p1ZhNuYmRFVHRyZHRnBltCCnxGV1YxeEQcDUp3ZlJAFFhafWEKFUlQQ25cOW9iHm90Yk5teXpaSGdhXHsBYStPTR1fdG5wHUIAZ0ZuZWVTeFQVWWliaFxSGFRQOARhQlRVQFVpBmBObEZmAUlKdU9gW0VFbHJkXW0Ffko6cmVTfEx3CXdvV1x+eWMDE2h1IXlJZ0J1VkNKe1cGBnZkcE1gdFJbbXdsWntMECo=",
        "gAAAAACWzMwMzIsIlRodSBKdWwgMTEgMjAyNCAwMzoxMDo0NiBHTVQrMDgwMCAo5Lit5Zu95qCH5YeG5pe26Ze0KSIsNDI5NDcwNTE1MiwxLCJNb3ppbGxhLzUuMCAoV2luZG93cyBOVCAxMC4wOyBXaW42NDsgeDY0KSBBcHBsZVdlYktpdC81MzcuMzYgKEtIVE1MLCBsaWtlIEdlY2tvKSBDaHJvbWUvMTI2LjAuMC4wIFNhZmFyaS81MzcuMzYgRWRnLzEyNi4wLjAuMCIsImh0dHBzOi8vY2RuLm9haXN0YXRpYy5jb20vX25leHQvc3RhdGljL2NodW5rcy9wYWdlcy9fYXBwLWMwOWZmNWY0MjQwMjcwZjguanMiLCJjL1pGWGkxeTNpMnpaS0EzSVQwNzRzMy9fIiwiemgtQ04iLCJ6aC1DTixlbixlbi1HQixlbi1VUyIsMTM1LCJ3ZWJraXRUZW1wb3JhcnlTdG9yYWdl4oiSW29iamVjdCBEZXByZWNhdGVkU3RvcmFnZVF1b3RhXSIsIl9yZWFjdExpc3RlbmluZ3NxZjF0ejFzNmsiLCJmZXRjaCIsMzY1NCwiNWU1NDUzNzItMzcyNy00ZDAyLTkwMDYtMzMwMDRjMWJmYTQ2Il0="
    )
    print(result)
