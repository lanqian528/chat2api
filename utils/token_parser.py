"""Token 解析器：从文件/文本中识别 ChatGPT 账号凭据。

职责：纯函数模块，不依赖 FastAPI / globals，易于单测。

识别规则（与 utils/routing.detect_token_type 一致）：
  - AccessToken: 以 'eyJhbGciOi' 或 'fk-' 开头
  - RefreshToken: 长度恰好 45 字符
  - 其他：归为 unknown

返回结构 ParseResult:
  {
    "refresh_tokens": [str, ...],  # 去重后
    "access_tokens":  [str, ...],
    "unknown":        [str, ...],
    "stats":          {refresh_count, access_count, unknown_count, total, source},
    "warnings":       [str, ...],
  }
"""

import json
import re
from typing import Dict, List, Optional, Set


# 候选字符串扫描：长度 ≥ 20 的字母数字 / 下划线 / 连字符 / 点 连串
# JWT 含 '.'，RefreshToken 含字母数字
_TOKEN_CANDIDATE_RE = re.compile(r"[A-Za-z0-9_\-\.]{20,}")

# JSON 中的 token 字段名（大小写不敏感）
_TOKEN_KEY_NAMES = {
    "refresh_token", "refreshtoken", "refresh",
    "access_token", "accesstoken", "accesstoken",
    "token", "session_token", "sessiontoken",
}


def _classify(token: str) -> str:
    """返回 'session' | 'access' | 'refresh' | 'unknown'。

    与 utils/routing.detect_token_type 规则保持一致：
      - session: 'sess-' 前缀（chatgpt.com 网页 session cookie，带前缀存储）
      - access: 'eyJhbGciOi' / 'fk-' 开头
      - refresh: 'rt_' 前缀且长度 ≥ 60（新版 Auth0 格式）或 长度 45（老版）
    """
    if not token:
        return "unknown"
    if token.startswith("sess-"):
        return "session"
    if token.startswith("eyJhbGciOi") or token.startswith("fk-"):
        return "access"
    if token.startswith("rt_") and len(token) >= 60:
        return "refresh"
    if len(token) == 45:
        return "refresh"
    return "unknown"


def _collect_from_json(obj, bucket: Set[str]) -> None:
    """递归扫描 JSON，抽取所有看起来像 token 的字符串。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            key_lower = str(k).lower()
            if isinstance(v, str):
                # 命名约定优先：字段名命中 token 关键词 → 整值入库
                if key_lower in _TOKEN_KEY_NAMES:
                    stripped = v.strip()
                    if stripped:
                        bucket.add(stripped)
                else:
                    # 普通字段：按候选正则扫描
                    for m in _TOKEN_CANDIDATE_RE.findall(v):
                        bucket.add(m)
            else:
                _collect_from_json(v, bucket)
    elif isinstance(obj, list):
        for item in obj:
            _collect_from_json(item, bucket)
    elif isinstance(obj, str):
        for m in _TOKEN_CANDIDATE_RE.findall(obj):
            bucket.add(m)
    # 其他类型（数字、布尔、None）忽略


def _build_result(raw_tokens: Set[str], source: str, warnings: Optional[List[str]] = None) -> Dict:
    session: List[str] = []
    refresh: List[str] = []
    access: List[str] = []
    unknown: List[str] = []
    for t in raw_tokens:
        t = (t or "").strip()
        if not t:
            continue
        kind = _classify(t)
        if kind == "session":
            session.append(t)
        elif kind == "refresh":
            refresh.append(t)
        elif kind == "access":
            access.append(t)
        else:
            unknown.append(t)

    session_set = sorted(set(session))
    refresh_set = sorted(set(refresh))
    access_set = sorted(set(access))
    unknown_set = sorted(set(unknown))

    total = len({*session_set, *refresh_set, *access_set, *unknown_set})

    return {
        "session_tokens": session_set,
        "refresh_tokens": refresh_set,
        "access_tokens": access_set,
        "unknown": unknown_set,
        "stats": {
            "session_count": len(session_set),
            "refresh_count": len(refresh_set),
            "access_count": len(access_set),
            "unknown_count": len(unknown_set),
            "total": total,
            "source": source,
        },
        "warnings": warnings or [],
    }


def parse_text(content: str) -> Dict:
    """按行扫描纯文本。

    规则：
      - 空行跳过
      - '#' 开头行视为注释跳过
      - 支持 "token,account_id" 格式：取逗号前部分
    """
    if not content:
        return _build_result(set(), source="text", warnings=["文件内容为空"])

    tokens: Set[str] = set()
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 形如 "token,account_id" 取首段；无逗号则整行
        primary = line.split(",", 1)[0].strip()
        if primary:
            tokens.add(primary)

    warnings: List[str] = []
    if not tokens:
        warnings.append("未从文件中识别到任何 token 候选")

    return _build_result(tokens, source="text", warnings=warnings)


def parse_json(content: str) -> Dict:
    """尝试解析 JSON；失败则回退按纯文本扫描。"""
    if not content:
        return _build_result(set(), source="json", warnings=["文件内容为空"])

    try:
        obj = json.loads(content)
    except json.JSONDecodeError as e:
        # 退化为文本扫描（避免一个括号错误就丢掉整个文件）
        fallback = parse_text(content)
        fallback["stats"]["source"] = "json-fallback"
        fallback.setdefault("warnings", []).append(f"JSON 解析失败，已回退文本扫描: {e}")
        return fallback

    tokens: Set[str] = set()
    _collect_from_json(obj, tokens)

    warnings: List[str] = []
    if not tokens:
        warnings.append("JSON 中未识别到任何 token 候选")

    return _build_result(tokens, source="json", warnings=warnings)


def parse_file(filename: str, content: bytes) -> Dict:
    """根据扩展名路由到对应解析器。"""
    ext = ""
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[-1].lower()

    # 解码：UTF-8 优先，GBK 兜底
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = content.decode("gbk")
        except UnicodeDecodeError:
            return _build_result(
                set(),
                source=ext or "bin",
                warnings=["文件编码不支持（需 UTF-8 或 GBK）"],
            )

    if ext == "json":
        return parse_json(text)
    return parse_text(text)


def mask_token(token: str) -> str:
    """前端预览用：显示前 6 + 后 4，防止整屏泄漏。"""
    if not token:
        return ""
    if len(token) <= 12:
        return token[:3] + "***" + token[-2:]
    return f"{token[:6]}...{token[-4:]}"
