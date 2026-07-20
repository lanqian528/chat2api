"""无状态头部工具函数。

供 ChatService 及其 Mixin 类型化和清洗 HTTP 头部使用。
原始位置：chatgpt/ChatService.py:46-66
"""

import json


def _stringify_header_value(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _sanitize_headers(headers):
    clean = {}
    for key, value in (headers or {}).items():
        if not key:
            continue
        value = _stringify_header_value(value)
        if value is not None:
            clean[str(key)] = value
    return clean
