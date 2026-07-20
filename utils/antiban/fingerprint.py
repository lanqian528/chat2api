"""指纹持久化强化。

职责：
  1. 以 fp_map 为底，扩展附加字段并持久化（screen、cores、device_memory 等）；
  2. 保证同一 token/账号在多次请求间指纹不变（防漂移）；
  3. 提供只读访问给 proofofWork/ChatService，避免直接修改 fp_map 污染。

注意：UA/impersonate/oai-device-id 仍由 chatgpt/fp.py 创建；
本模块只在其基础上补齐字段，不替代 fp.py。
"""

import hashlib
import json
import random
import threading
import time
import uuid
from typing import Dict, Optional

import utils.globals as globals
from utils import configs
from utils.Logger import logger

_write_lock = threading.Lock()

_SCREEN_POOL = [
    {"width": 1920, "height": 1080, "color_depth": 24},
    {"width": 2560, "height": 1440, "color_depth": 24},
    {"width": 1920, "height": 1200, "color_depth": 24},
    {"width": 2560, "height": 1600, "color_depth": 30},
    {"width": 1680, "height": 1050, "color_depth": 24},
]
_CORES_POOL = [4, 8, 8, 8, 12, 16]
_DEVICE_MEMORY_POOL = [4, 8, 8, 16]
# 真实设备 devicePixelRatio：绝大多数设备是 1.0（普通屏）或 2.0（Retina/HiDPI）
# 1.5、1.25、2.5 等占比极小；硬编码 1.5 是典型自动化客户端特征
_PIXEL_RATIO_POOL = [1.0, 1.0, 2.0, 2.0, 2.0, 1.5]
# 浏览器窗口实际可视区（page_height/width）：真实用户通常最大化 / 大部分屏幕
# page_height 必然 < screen_height，page_width <= screen_width
_VIEWPORT_RATIO_POOL = [0.95, 0.92, 0.85, 0.78]  # 占屏比例

# ============================================================
# 扩展指纹池（PR-补强：覆盖 sentinel / CF 常用判别维度）
# 设计原则：所有派生字段从 fp 内已有字段推导，token 级稳定，与 screen/cores 同样持久化。
# ============================================================

# navigator.platform 字符串（强一致性：必须与 sec-ch-ua-platform 对应）
_NAV_PLATFORM_MAP = {
    "macos": "MacIntel",
    "windows": "Win32",
    "linux": "Linux x86_64",
    "chromeos": "Linux x86_64",
    "chrome os": "Linux x86_64",
}
# 各系统任务栏/Dock 占用的高度（screen.height - avail_height）
_TASKBAR_OFFSET = {"MacIntel": 25, "Win32": 40, "Linux x86_64": 27}
# WebGL vendor/renderer 必须与 platform 一致（macOS=Apple/Intel，Win=ANGLE，Linux=Mesa）
_WEBGL_BY_PLATFORM = {
    "MacIntel": [
        ("Apple Inc.", "Apple M1"),
        ("Apple Inc.", "Apple M2"),
        ("Apple Inc.", "Apple M3"),
        ("Apple Inc.", "Apple M1 Pro"),
        ("Intel Inc.", "Intel Iris OpenGL Engine"),
    ],
    "Win32": [
        ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 6700 XT Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ],
    "Linux x86_64": [
        ("Mesa", "Mesa Intel(R) Graphics (ADL-P GT2)"),
        ("Mesa/X.org", "llvmpipe (LLVM 15.0.7, 256 bits)"),
    ],
}
# navigator.languages：与 accept-language 大致对齐；多数英语用户为 ["en-US","en"]
_LANGUAGES_POOL = [
    ["en-US", "en"],
    ["en-US", "en"],
    ["en-US", "en"],
    ["en-US", "en", "zh-CN"],
    ["en-GB", "en"],
    ["zh-CN", "zh", "en-US", "en"],
]
# matchMedia prefers-color-scheme：浅色占 70%
_COLOR_SCHEME_POOL = ["light"] * 7 + ["dark"] * 3
# matchMedia prefers-reduced-motion：no-preference 占 95%
_REDUCED_MOTION_POOL = ["no-preference"] * 19 + ["reduce"] * 1
# AudioContext.sampleRate：48000 占主流；少量 macOS/USB DAC 用 44100
_AUDIO_SAMPLE_POOL = [48000] * 9 + [44100] * 1
# NetworkInformation.effectiveType：宽带绝大多数为 4g
_CONNECTION_EFFECTIVE_TYPE_POOL = ["4g"] * 19 + ["3g"] * 1

# 国家 → languages 优先列表（H2: 与 antiban geo 级联，避免 IP/语言矛盾）
_COUNTRY_LANGUAGES = {
    "US": [["en-US", "en"], ["en-US", "en"], ["en-US", "en", "es"]],
    "GB": [["en-GB", "en"], ["en-GB", "en", "en-US"]],
    "CA": [["en-CA", "en"], ["en-CA", "en", "fr-CA"], ["fr-CA", "fr", "en-CA", "en"]],
    "AU": [["en-AU", "en"]],
    "JP": [["ja-JP", "ja", "en-US", "en"], ["ja", "en-US", "en"]],
    "KR": [["ko-KR", "ko", "en-US", "en"]],
    "SG": [["en-SG", "en", "zh-CN", "zh"], ["en-SG", "en"]],
    "HK": [["zh-HK", "zh", "en"], ["en-US", "en", "zh-HK"]],
    "TW": [["zh-TW", "zh", "en-US", "en"]],
    "DE": [["de-DE", "de", "en"], ["de", "en-US", "en"]],
    "FR": [["fr-FR", "fr", "en"], ["fr", "en-US", "en"]],
}

# 用户节奏画像（M1: time_since_loaded 不再纯随机；同账号保持一致的"用户性格"）
# 真实用户：快速浏览者 ~1-5s 提问；普通 ~5-30s；深思 ~30-120s（含读题/思考/打字）
_USER_PACE_POOL = ["fast"] * 3 + ["normal"] * 5 + ["slow"] * 2
_PACE_TIME_RANGE = {
    "fast":   (1500, 8000),
    "normal": (5000, 35000),
    "slow":   (20000, 120000),
}

# ============================================================
# T3: WebGL 完整指纹扩展池（按 platform 分桶，保持物理一致性）
# ============================================================
# max_texture_size：现代独显常见 16384；集显 8192；老旧 4096
_WEBGL_MAX_TEXTURE_BY_RENDERER = {
    "Apple": 16384,
    "NVIDIA": 16384,
    "AMD": 16384,
    "Intel(R) UHD": 8192,
    "Intel Iris": 16384,
    "Mesa": 8192,
    "llvmpipe": 8192,
}
# WebGL extensions：现代 Chrome 上每个 GPU 各自常见 ~30-35 项
# 用集合的哈希值作为指纹（同账号稳定，不同账号略有差异）
_WEBGL_EXTENSIONS_TEMPLATE = [
    "ANGLE_instanced_arrays", "EXT_blend_minmax", "EXT_color_buffer_half_float",
    "EXT_disjoint_timer_query", "EXT_float_blend", "EXT_frag_depth",
    "EXT_shader_texture_lod", "EXT_texture_compression_bptc",
    "EXT_texture_compression_rgtc", "EXT_texture_filter_anisotropic",
    "EXT_sRGB", "KHR_parallel_shader_compile", "OES_element_index_uint",
    "OES_fbo_render_mipmap", "OES_standard_derivatives", "OES_texture_float",
    "OES_texture_float_linear", "OES_texture_half_float",
    "OES_texture_half_float_linear", "OES_vertex_array_object",
    "WEBGL_color_buffer_float", "WEBGL_compressed_texture_s3tc",
    "WEBGL_compressed_texture_s3tc_srgb", "WEBGL_debug_renderer_info",
    "WEBGL_debug_shaders", "WEBGL_depth_texture", "WEBGL_draw_buffers",
    "WEBGL_lose_context", "WEBGL_multi_draw",
]

# ============================================================
# T2: Canvas / Font / AudioContext 指纹哈希池
# 真实环境下这些都是 sentinel.js 通过执行 JS 主动计算的哈希值。
# 我们作为 API 代理无法实际渲染 canvas/采样 audio，但**持久化 token 级稳定的代理哈希**：
#   - 同账号多次请求一致 → 不触发"指纹漂移"
#   - 不同账号分散 → 不触发"批量自动化"
# 这些值在未来 sentinel 主动采集时可注入相关字段。
# ============================================================
# 字体集合按 OS 分桶（真实系统默认安装字体的子集）
_FONTS_BY_PLATFORM = {
    "MacIntel": [
        "Apple SD Gothic Neo", "AppleMyungjo", "Arial", "Arial Black", "Arial Hebrew",
        "Avenir", "Avenir Next", "Charter", "Comic Sans MS", "Courier", "Courier New",
        "Geneva", "Georgia", "Helvetica", "Helvetica Neue", "Hiragino Sans",
        "Lucida Grande", "Menlo", "Monaco", "Optima", "PT Sans", "Palatino",
        "SF Mono", "SF Pro", "STIX", "Symbol", "Tahoma", "Times", "Times New Roman",
        "Trebuchet MS", "Verdana", "Zapfino",
    ],
    "Win32": [
        "Arial", "Arial Black", "Arial Narrow", "Cambria", "Cambria Math", "Candara",
        "Comic Sans MS", "Consolas", "Constantia", "Corbel", "Courier New", "Ebrima",
        "Franklin Gothic Medium", "Gabriola", "Gadugi", "Georgia", "Impact",
        "Lucida Console", "Lucida Sans Unicode", "Malgun Gothic", "Marlett",
        "Microsoft Sans Serif", "Microsoft YaHei", "MingLiU-ExtB", "Mongolian Baiti",
        "MS Gothic", "Palatino Linotype", "Segoe Print", "Segoe Script", "Segoe UI",
        "SimSun", "Sylfaen", "Symbol", "Tahoma", "Times New Roman", "Trebuchet MS",
        "Verdana", "Webdings", "Wingdings",
    ],
    "Linux x86_64": [
        "Bitstream Vera Sans", "Bitstream Vera Sans Mono", "Bitstream Vera Serif",
        "Courier 10 Pitch", "DejaVu Sans", "DejaVu Sans Mono", "DejaVu Serif",
        "Liberation Mono", "Liberation Sans", "Liberation Serif", "Nimbus Mono L",
        "Nimbus Roman No9 L", "Nimbus Sans L", "Noto Color Emoji", "Noto Mono",
        "Noto Sans", "Noto Sans Mono", "Noto Serif", "Source Code Pro", "Ubuntu",
        "Ubuntu Mono", "URW Bookman L", "URW Chancery L", "URW Gothic L",
        "URW Palladio L",
    ],
}

# AudioContext oscillator 输出基线值（不同 OS/硬件浮点 mantissa 略有差异）
# 真实 sentinel.js 采集 OSC + Analyser 后 sum() 取 4 位小数；我们模拟为按 platform 分桶的 base+jitter
_AUDIO_FP_BASE_BY_PLATFORM = {
    "MacIntel":      35.749561,
    "Win32":         35.748905,
    "Linux x86_64":  35.748734,
}

# T5: 国家 → 默认 IANA timezone（用于 fp 持久化，与 geo 模块 _GEO_DEFAULTS 保持一致）
_COUNTRY_TIMEZONE = {
    "US": "America/Los_Angeles", "JP": "Asia/Tokyo", "SG": "Asia/Singapore",
    "HK": "Asia/Hong_Kong", "TW": "Asia/Taipei", "KR": "Asia/Seoul",
    "DE": "Europe/Berlin", "GB": "Europe/London", "CA": "America/Toronto",
    "FR": "Europe/Paris", "AU": "Australia/Sydney",
}

# ============================================================
# D2: WebGPU adapter 持久化（与 webgl renderer 强一致）
# Chrome 113+ 暴露 navigator.gpu.requestAdapter() → architecture/vendor/device/description
# ============================================================
# renderer 关键词 → (architecture, vendor)
_WEBGPU_ARCH_BY_RENDERER = {
    "Apple M1":     ("apple-silicon", "apple"),
    "Apple M2":     ("apple-silicon", "apple"),
    "Apple M3":     ("apple-silicon", "apple"),
    "Apple M1 Pro": ("apple-silicon", "apple"),
    "Intel Iris":   ("haswell",      "intel"),
    "Intel(R) UHD": ("kabylake",     "intel"),
    "NVIDIA":       ("ampere",       "nvidia"),
    "AMD":          ("rdna-2",       "amd"),
    "Mesa":         ("gen-9",        "mesa"),
    "llvmpipe":     ("software",     "mesa"),
}

# ============================================================
# D3: WebRTC ICE 候选模拟（持久化模拟值；curl 不发但 sentinel.js 可主动检测）
# 真实浏览器通过 RTCPeerConnection 收集本地 IP；现代 Chrome 默认 mDNS 隐藏（.local）
# ============================================================
_WEBRTC_LOCAL_IP_POOLS = [
    # 主流家庭/办公私网段
    lambda r: f"192.168.{r.randint(0, 9)}.{r.randint(2, 254)}",
    lambda r: f"192.168.1.{r.randint(2, 254)}",
    lambda r: f"10.0.{r.randint(0, 255)}.{r.randint(2, 254)}",
    lambda r: f"172.{r.randint(16, 31)}.{r.randint(0, 255)}.{r.randint(2, 254)}",
]
# Chrome 默认 STUN 服务器（无显式配置时使用 Google STUN）
_WEBRTC_STUN_SERVERS = [
    "stun:stun.l.google.com:19302",
    "stun:stun1.l.google.com:19302",
]


def _platform_key_from_ch(sec_ch_ua_platform):
    """从 sec-ch-ua-platform 头值（形如 '"macOS"'）提取小写键。"""
    if not sec_ch_ua_platform:
        return None
    return str(sec_ch_ua_platform).strip().strip('"').lower()


def _derive_nav_platform(fp):
    """根据 sec-ch-ua-platform 推导 navigator.platform；缺失时回退 Win32。"""
    key = _platform_key_from_ch(fp.get("sec-ch-ua-platform"))
    return _NAV_PLATFORM_MAP.get(key, "Win32")


def _persist_fp() -> None:
    with _write_lock:
        with open(globals.FP_FILE, "w", encoding="utf-8") as f:
            json.dump(globals.fp_map, f, indent=4, ensure_ascii=False)


def ensure_extended(token: str) -> Dict:
    """确保 fp_map[token] 含扩展字段；缺失则补齐并持久化。返回 fp 副本。"""
    if not token:
        return {}
    fp = globals.fp_map.setdefault(token, {})
    dirty = False

    if "screen" not in fp:
        fp["screen"] = random.choice(_SCREEN_POOL)
        dirty = True
    if "hardware_concurrency" not in fp:
        fp["hardware_concurrency"] = random.choice(_CORES_POOL)
        dirty = True
    if "device_memory" not in fp:
        fp["device_memory"] = random.choice(_DEVICE_MEMORY_POOL)
        dirty = True
    if "pixel_ratio" not in fp:
        fp["pixel_ratio"] = random.choice(_PIXEL_RATIO_POOL)
        dirty = True
    # 浏览器实际可视区：基于 screen 推导，token 级稳定（同账号多次请求不再抖动）
    if "viewport" not in fp:
        screen = fp.get("screen") or {}
        sw = int(screen.get("width") or 1920)
        sh = int(screen.get("height") or 1080)
        ratio_w = random.choice(_VIEWPORT_RATIO_POOL)
        ratio_h = random.choice(_VIEWPORT_RATIO_POOL)
        fp["viewport"] = {
            "page_width": int(sw * ratio_w),
            "page_height": int(sh * ratio_h - 120),  # 减去浏览器 chrome 高度（地址栏+标签栏）
            "screen_width": sw,
            "screen_height": sh,
        }
        dirty = True

    # ====== 扩展指纹（sentinel / CF 常用维度） ======
    # navigator.platform：与 sec-ch-ua-platform 一致；老 fp 缺 CH 头时回退 Win32
    if "nav_platform" not in fp:
        fp["nav_platform"] = _derive_nav_platform(fp)
        dirty = True

    # screen 内部补强：avail_width/avail_height/pixel_depth
    screen = fp.get("screen") or {}
    if isinstance(screen, dict):
        screen_dirty = False
        if "avail_width" not in screen:
            screen["avail_width"] = int(screen.get("width") or 1920)
            screen_dirty = True
        if "avail_height" not in screen:
            offset = _TASKBAR_OFFSET.get(fp.get("nav_platform", "Win32"), 40)
            screen["avail_height"] = int((screen.get("height") or 1080)) - offset
            screen_dirty = True
        if "pixel_depth" not in screen:
            screen["pixel_depth"] = int(screen.get("color_depth") or 24)
            screen_dirty = True
        if screen_dirty:
            fp["screen"] = screen
            dirty = True

    # WebGL vendor/renderer + 完整扩展指纹（T3）：按 nav_platform 分桶；不匹配时回退 Win32
    if "webgl" not in fp:
        pool = _WEBGL_BY_PLATFORM.get(fp.get("nav_platform"), _WEBGL_BY_PLATFORM["Win32"])
        vendor, renderer = random.choice(pool)
        # 按 renderer 关键词推断 max_texture_size
        max_tex = 8192
        for key, val in _WEBGL_MAX_TEXTURE_BY_RENDERER.items():
            if key in renderer:
                max_tex = val
                break
        # extensions：从模板池中随机选 24-32 项（真实数量范围），稳定排序后哈希
        ext_count = random.randint(24, 32)
        ext_subset = sorted(random.sample(_WEBGL_EXTENSIONS_TEMPLATE,
                                          min(ext_count, len(_WEBGL_EXTENSIONS_TEMPLATE))))
        ext_hash = hashlib.sha256("|".join(ext_subset).encode()).hexdigest()[:16]
        # unmasked_* 是 WEBGL_debug_renderer_info 暴露的真实值（Chrome 已限制为 generic）
        # 现代 Chrome 138+ 默认隐藏后返回与普通 vendor/renderer 相同；老版本暴露驱动细节
        unmasked_vendor = vendor
        unmasked_renderer = renderer
        fp["webgl"] = {
            "vendor": vendor,
            "renderer": renderer,
            "max_texture_size": max_tex,
            "max_viewport_dims": [max_tex, max_tex],
            "shading_language_version": "WebGL GLSL ES 1.0 (OpenGL ES GLSL ES 1.0 Chromium)",
            "extensions_hash": ext_hash,
            "extensions_count": len(ext_subset),
            "unmasked_vendor": unmasked_vendor,
            "unmasked_renderer": unmasked_renderer,
        }
        dirty = True

    # navigator.languages：与 antiban geo 级联（H2）→ 与 accept-language / IP 地域一致
    if "languages" not in fp:
        languages = None
        try:
            # 通过桶绑定的 proxy_url 反查地域
            from utils.antiban import bucket as _bucket
            from utils.antiban import geo as _geo
            proxy_url = _bucket.get_bucket_proxy(token)
            geo_info = _geo.get_geo(proxy_url) if proxy_url else None
            country = (geo_info or {}).get("country")
            if country and country in _COUNTRY_LANGUAGES:
                languages = random.choice(_COUNTRY_LANGUAGES[country])
        except Exception:
            languages = None
        fp["languages"] = languages or random.choice(_LANGUAGES_POOL)
        dirty = True

    # maxTouchPoints：桌面=0；当前主流场景 device_tuple 都是 desktop
    if "max_touch_points" not in fp:
        try:
            from utils import configs as _configs
            device_tuple = getattr(_configs, "device_tuple", None)
        except Exception:
            device_tuple = None
        is_mobile = bool(device_tuple) and any(d in ("mobile", "tablet") for d in device_tuple)
        fp["max_touch_points"] = 5 if is_mobile else 0
        dirty = True

    # color_scheme：替代 ChatService 中硬编码的 is_dark_mode
    if "color_scheme" not in fp:
        fp["color_scheme"] = random.choice(_COLOR_SCHEME_POOL)
        dirty = True

    # prefers-reduced-motion：95% no-preference
    if "prefers_reduced_motion" not in fp:
        fp["prefers_reduced_motion"] = random.choice(_REDUCED_MOTION_POOL)
        dirty = True

    # color_gamut：与 pixel_ratio + platform 协同（Retina Mac 才有 p3）
    if "color_gamut" not in fp:
        pr = float(fp.get("pixel_ratio") or 1.0)
        is_retina_mac = fp.get("nav_platform") == "MacIntel" and pr >= 2.0
        fp["color_gamut"] = random.choice(["p3", "srgb"]) if is_retina_mac else "srgb"
        dirty = True

    # NetworkInformation：模拟宽带 4g
    if "connection" not in fp:
        fp["connection"] = {
            "effective_type": random.choice(_CONNECTION_EFFECTIVE_TYPE_POOL),
            "downlink": round(random.uniform(8.0, 15.0), 2),
            "rtt": random.randint(50, 150),
            "save_data": False,
        }
        dirty = True

    # AudioContext 指纹
    if "audio" not in fp:
        fp["audio"] = {
            "sample_rate": random.choice(_AUDIO_SAMPLE_POOL),
            "base_latency": round(random.uniform(0.005, 0.012), 6),
        }
        dirty = True

    # 用户节奏画像（M1）：token 级稳定，决定 time_since_loaded 抽样分布
    if "user_pace" not in fp:
        fp["user_pace"] = random.choice(_USER_PACE_POOL)
        dirty = True

    # 虚拟页面加载偏移（M2）：让 perf_counter / time_since_loaded 起点 token 级稳定
    # 真实用户进入聊天页后通常停留 30s-30min，PoW 用 (now - load) 而非进程级 perf_counter
    if "virtual_page_load_ms" not in fp:
        # 存储相对偏移 (ms)：模拟"用户已在页面停留 30s-1800s"
        fp["virtual_page_load_ms"] = round(random.uniform(30_000, 1_800_000), 3)
        dirty = True

    # ====== T2: Canvas / Font / Audio FP 哈希持久化（sentinel.js 主采项的代理值） ======
    # token 级稳定：同账号永不变；不同账号自然分散（基于 token + platform 派生）
    if "canvas_hash" not in fp:
        # 真实 sentinel.js 计算的是 canvas.toDataURL() 的 MD5/SHA1 截断哈希
        # 我们用 token + nav_platform + screen 派生：保证 token 级稳定且系统级有差异
        nav = fp.get("nav_platform", "Win32")
        screen = fp.get("screen", {})
        seed = f"canvas|{token}|{nav}|{screen.get('width')}x{screen.get('height')}"
        fp["canvas_hash"] = hashlib.sha256(seed.encode()).hexdigest()[:32]
        dirty = True

    if "font_list_hash" not in fp:
        # 按 platform 选典型字体集，hash 之
        nav = fp.get("nav_platform", "Win32")
        fonts = _FONTS_BY_PLATFORM.get(nav, _FONTS_BY_PLATFORM["Win32"])
        # 同 OS 内部稍作 jitter（个别字体存在性差异）：取池子的 80%-100% 子集，token 决定
        rng = random.Random(token + "|fonts")
        keep_count = rng.randint(int(len(fonts) * 0.8), len(fonts))
        subset = sorted(rng.sample(fonts, keep_count))
        fp["font_list_hash"] = hashlib.sha256("|".join(subset).encode()).hexdigest()[:32]
        fp["font_list_count"] = len(subset)
        dirty = True

    if "audio_fp_hash" not in fp:
        nav = fp.get("nav_platform", "Win32")
        base = _AUDIO_FP_BASE_BY_PLATFORM.get(nav, _AUDIO_FP_BASE_BY_PLATFORM["Win32"])
        # token 决定微观 jitter（10^-6 量级，模拟硬件浮点指纹差异）
        rng = random.Random(token + "|audio")
        jitter = rng.uniform(-0.0001, 0.0001)
        fp["audio_fp_hash"] = round(base + jitter, 6)
        dirty = True

    # ====== T5: Intl / IANA timezone 持久化（与 antiban geo 级联） ======
    if "timezone" not in fp or "intl_locale" not in fp:
        timezone_val = None
        locale_val = None
        try:
            from utils.antiban import bucket as _bucket
            from utils.antiban import geo as _geo
            proxy_url = _bucket.get_bucket_proxy(token)
            geo_info = _geo.get_geo(proxy_url) if proxy_url else None
            if geo_info:
                timezone_val = geo_info.get("timezone")
                locale_val = geo_info.get("oai_language")  # 如 "en-US"/"ja-JP"
        except Exception:
            pass
        # 兜底：configs 默认值
        fp["timezone"] = timezone_val or configs.client_timezone
        # locale 优先用 languages[0]（已与 geo 级联）
        if not locale_val and isinstance(fp.get("languages"), list) and fp["languages"]:
            locale_val = fp["languages"][0]
        fp["intl_locale"] = locale_val or configs.oai_language
        dirty = True

    # ====== D2: WebGPU adapter 持久化（与 webgl renderer 强一致） ======
    if "webgpu" not in fp:
        wg = fp.get("webgl") or {}
        renderer = wg.get("renderer", "")
        arch, vendor_kw = "x86-64", "intel"
        for kw, (a, v) in _WEBGPU_ARCH_BY_RENDERER.items():
            if kw in renderer:
                arch, vendor_kw = a, v
                break
        # device 取 webgl renderer 中的可读 GPU 名（去除 ANGLE 包装）
        device_name = renderer
        if "ANGLE (" in renderer:
            # ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 ..., D3D11) → NVIDIA GeForce RTX 3060
            import re as _re
            m = _re.search(r"ANGLE \([^,]+,\s*([^,]+?)\s+Direct3D", renderer)
            if m:
                device_name = m.group(1)
        fp["webgpu"] = {
            "architecture": arch,
            "vendor": vendor_kw,
            "device": device_name[:80],  # 截断防止过长
            "description": f"{vendor_kw.capitalize()} {device_name[:60]}",
        }
        dirty = True

    # ====== D3: WebRTC ICE 候选模拟（local_ip + stun + candidate_type） ======
    if "webrtc" not in fp:
        rng = random.Random(token + "|webrtc")
        local_ip_gen = rng.choice(_WEBRTC_LOCAL_IP_POOLS)
        # mDNS 模式：现代 Chrome 默认开启，本地 IP 被替换为 .local 唯一标识符
        mdns_id = uuid.UUID(bytes=hashlib.sha256(("mdns|" + token).encode()).digest()[:16])
        fp["webrtc"] = {
            "local_ip": local_ip_gen(rng),
            "mdns_hostname": f"{mdns_id}.local",
            "stun_server": rng.choice(_WEBRTC_STUN_SERVERS),
            "ice_candidate_type": "host",  # mDNS 后真实 IP 不外泄，类型仍为 host
        }
        dirty = True

    if dirty:
        try:
            _persist_fp()
            logger.info(f"[antiban] fingerprint extended for token={token[:12]}...")
        except Exception as e:  # pragma: no cover
            logger.error(f"[antiban] failed to persist extended fp: {e}")

    return dict(fp)


def get_stable_fp(token: str) -> Optional[Dict]:
    if not configs.enable_antiban or not token:
        return None
    fp = globals.fp_map.get(token)
    if not fp:
        return None
    return dict(fp)


def get_screen_resolution_sum(token: str) -> Optional[int]:
    """供 proofofWork.get_config 使用：返回 width+height 总和。"""
    if not configs.enable_antiban or not token:
        return None
    fp = globals.fp_map.get(token, {})
    screen = fp.get("screen")
    if isinstance(screen, dict) and "width" in screen and "height" in screen:
        return int(screen["width"]) + int(screen["height"])
    return None


def get_hardware_concurrency(token: str) -> Optional[int]:
    if not configs.enable_antiban or not token:
        return None
    val = globals.fp_map.get(token, {}).get("hardware_concurrency")
    return int(val) if val else None


def get_contextual_info(token: str) -> Optional[Dict]:
    """返回 token 级稳定的 client_contextual_info 数据，供 ChatService 注入到 chat_request。

    未启用 antiban 或 fp 未持久化 → 返回 None，调用方走老逻辑（随机）。
    """
    if not configs.enable_antiban or not token:
        return None
    fp = globals.fp_map.get(token, {})
    viewport = fp.get("viewport")
    pixel_ratio = fp.get("pixel_ratio")
    if not viewport:
        return None
    return {
        "page_width": int(viewport.get("page_width") or 1820),
        "page_height": int(viewport.get("page_height") or 960),
        "screen_width": int(viewport.get("screen_width") or 1920),
        "screen_height": int(viewport.get("screen_height") or 1080),
        "pixel_ratio": float(pixel_ratio) if pixel_ratio else 2.0,
        # token 级稳定的 color_scheme，供 is_dark_mode 派生
        "color_scheme": fp.get("color_scheme") or "light",
        # T5: Intl 字段供未来注入 chat_request / payload
        "timezone": fp.get("timezone"),
        "intl_locale": fp.get("intl_locale"),
    }


def get_timezone(token: str) -> Optional[str]:
    """供 proofofWork.get_parse_time 使用：返回 token 级稳定的 IANA timezone。"""
    if not configs.enable_antiban or not token:
        return None
    val = globals.fp_map.get(token, {}).get("timezone")
    return str(val) if val else None


def get_color_scheme(token: str) -> Optional[str]:
    """返回 token 级稳定的 color_scheme（"light"/"dark"）；未启用或缺失 → None。"""
    if not configs.enable_antiban or not token:
        return None
    val = globals.fp_map.get(token, {}).get("color_scheme")
    return val if val in ("light", "dark") else None


def get_user_pace_range(token: str) -> Optional[tuple]:
    """供 ChatService 派生 time_since_loaded：返回该 token 的 (min_ms, max_ms) 范围。

    未启用或缺失 → None（调用方走默认随机区间）。
    """
    if not configs.enable_antiban or not token:
        return None
    pace = globals.fp_map.get(token, {}).get("user_pace")
    return _PACE_TIME_RANGE.get(pace) if pace else None


def get_virtual_page_load_ms(token: str) -> Optional[float]:
    """供 proofofWork 派生 perf_counter：返回 token 级稳定的页面加载偏移（毫秒）。"""
    if not configs.enable_antiban or not token:
        return None
    val = globals.fp_map.get(token, {}).get("virtual_page_load_ms")
    return float(val) if val is not None else None


def is_fingerprint_locked(token: str) -> bool:
    return bool(globals.fp_map.get(token, {}).get("user-agent"))
