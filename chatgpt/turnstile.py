import json
import random
import time
from collections import OrderedDict, defaultdict
from typing import Any, Callable, Dict, List

import pybase64


class OrderedMap:
    def __init__(self):
        self.map = OrderedDict()

    def add(self, key: str, value: Any):
        self.map[key] = value

    def to_json(self):
        return json.dumps(self.map)

    def __str__(self):
        return self.to_json()


TurnTokenList = List[List[Any]]
FloatMap = Dict[float, Any]
StringMap = Dict[str, Any]
FuncType = Callable[..., Any]

start_time = time.time()


def get_turnstile_token(dx: str, p: str) -> str:
    decoded_bytes = pybase64.b64decode(dx)
    return process_turnstile_token(decoded_bytes.decode(), p)


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
        return f"{input_val:.16g}"
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
        print(f"Type of input is: {type(input_val)}")
        return str(input_val)


def get_func_map() -> FloatMap:
    process_map: FloatMap = defaultdict(lambda: None)

    def func_1(e: float, t: float):
        e_str = to_str(process_map[e])
        t_str = to_str(process_map[t])
        if e_str is not None and t_str is not None:
            res = process_turnstile_token(e_str, t_str)
            process_map[e] = res
        else:
            print(f"Warning: Unable to process func_1 for e={e}, t={t}")

    def func_2(e: float, t: Any):
        process_map[e] = t

    def func_5(e: float, t: float):
        n = process_map[e]
        tres = process_map[t]
        if n is None:
            process_map[e] = tres
        elif is_slice(n):
            nt = n + [tres] if tres is not None else n
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
            try:
                token_list = json.loads(tv)
                process_map[e] = token_list
            except json.JSONDecodeError:
                print(f"Warning: Unable to parse JSON for key {t}")
                process_map[e] = None
        else:
            print(f"Warning: Value for key {t} is not a string")
            process_map[e] = None

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
        if ev is not None and callable(tv):
            tv(*i)

    process_map.update({
        1: func_1, 2: func_2, 5: func_5, 6: func_6, 24: func_24, 7: func_7,
        17: func_17, 8: func_8, 10: "window", 14: func_14, 15: func_15,
        18: func_18, 19: func_19, 20: func_20, 21: func_21, 23: func_23
    })

    return process_map


def process_turnstile(dx: str, p: str) -> str:
    tokens = get_turnstile_token(dx, p)
    token_list = json.loads(tokens)
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
                print(f"Warning: No function found for key {e}")
        except Exception as exc:
            print(f"Error processing token {token}: {exc}")

    return res


if __name__ == "__main__":
    result = process_turnstile(
        "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BVAcbWEaeXJ5SGFXdE9nR35Abllcb2JyUXkAUBBGSzx1W29LYmN4QmNeWB1tdUMRdHZsfGN6cUt4alVEEG9hNAx6R0wCdlUAAF93fxl5VHMZUFweFmNQHn9kFC4=",
        "gAAAAACWzMwMzIsIlNhdCBKdW4gMjkgMjAyNCAwMjo1MDo1MCBHTVQrMDgwMCAo5Lit5Zu95qCH5YeG5pe26Ze0KSIsNDI5NDcwNTE1MiwyLCJNb3ppbGxhLzUuMCAoV2luZG93cyBOVCAxMC4wOyBXaW42NDsgeDY0KSBBcHBsZVdlYktpdC81MzcuMzYgKEtIVE1MLCBsaWtlIEdlY2tvKSBDaHJvbWUvMTI2LjAuMC4wIFNhZmFyaS81MzcuMzYgRWRnLzEyNi4wLjAuMCIsImh0dHBzOi8vY2RuLm9haXN0YXRpYy5jb20vX25leHQvc3RhdGljL2NodW5rcy82NDQxLWY5M2YxM2ZkMTc1MTJkMDguanMiLG51bGwsInpoLUNOIiwiemgtQ04sZW4sZW4tR0IsZW4tVVMiLDE3Mywid2Via2l0R2V0VXNlck1lZGlh4oiSZnVuY3Rpb24gd2Via2l0R2V0VXNlck1lZGlhKCkgeyBbbmF0aXZlIGNvZGVdIH0iLCJfcmVhY3RMaXN0ZW5pbmc5ejQ0dHp5bzNmIiwib25jb250ZXh0bG9zdCIsODE4MiwiNTBkYWYzNTAtN2EyZS00ODMzLTk2MmQtMDQ4MjAzNmZlMDZiIl0="
    )
    print(result)
