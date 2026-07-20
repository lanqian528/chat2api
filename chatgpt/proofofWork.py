import hashlib
import json
import random
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

import pybase64
import diskcache as dc

from utils.Logger import logger
from utils.configs import conversation_only, client_timezone, client_timezone_offset_min, accept_language, oai_language

cores = [8, 16, 24, 32]
timeLayout = "%a %b %d %Y %H:%M:%S"

cache = dc.Cache('./data/pow_config_cache')
cached_scripts = []
cached_dpl = ""
cached_time = 0
cached_require_proof = ""

navigator_key = [
    "registerProtocolHandler−function registerProtocolHandler() { [native code] }",
    "storage−[object StorageManager]",
    "locks−[object LockManager]",
    "appCodeName−Mozilla",
    "permissions−[object Permissions]",
    "share−function share() { [native code] }",
    "webdriver−false",
    "managed−[object NavigatorManagedData]",
    "canShare−function canShare() { [native code] }",
    "vendor−Google Inc.",
    "vendor−Google Inc.",
    "mediaDevices−[object MediaDevices]",
    "vibrate−function vibrate() { [native code] }",
    "storageBuckets−[object StorageBucketManager]",
    "mediaCapabilities−[object MediaCapabilities]",
    "getGamepads−function getGamepads() { [native code] }",
    "bluetooth−[object Bluetooth]",
    "share−function share() { [native code] }",
    "cookieEnabled−true",
    "virtualKeyboard−[object VirtualKeyboard]",
    "product−Gecko",
    "mediaDevices−[object MediaDevices]",
    "canShare−function canShare() { [native code] }",
    "getGamepads−function getGamepads() { [native code] }",
    "product−Gecko",
    "xr−[object XRSystem]",
    "clipboard−[object Clipboard]",
    "storageBuckets−[object StorageBucketManager]",
    "unregisterProtocolHandler−function unregisterProtocolHandler() { [native code] }",
    "productSub−20030107",
    "login−[object NavigatorLogin]",
    "vendorSub−",
    "login−[object NavigatorLogin]",
    "getInstalledRelatedApps−function getInstalledRelatedApps() { [native code] }",
    "mediaDevices−[object MediaDevices]",
    "locks−[object LockManager]",
    "webkitGetUserMedia−function webkitGetUserMedia() { [native code] }",
    "vendor−Google Inc.",
    "xr−[object XRSystem]",
    "mediaDevices−[object MediaDevices]",
    "virtualKeyboard−[object VirtualKeyboard]",
    "virtualKeyboard−[object VirtualKeyboard]",
    "appName−Netscape",
    "storageBuckets−[object StorageBucketManager]",
    "presentation−[object Presentation]",
    "onLine−true",
    "mimeTypes−[object MimeTypeArray]",
    "credentials−[object CredentialsContainer]",
    "presentation−[object Presentation]",
    "getGamepads−function getGamepads() { [native code] }",
    "vendorSub−",
    "virtualKeyboard−[object VirtualKeyboard]",
    "serviceWorker−[object ServiceWorkerContainer]",
    "xr−[object XRSystem]",
    "product−Gecko",
    "keyboard−[object Keyboard]",
    "gpu−[object GPU]",
    "getInstalledRelatedApps−function getInstalledRelatedApps() { [native code] }",
    "webkitPersistentStorage−[object DeprecatedStorageQuota]",
    "doNotTrack",
    "clearAppBadge−function clearAppBadge() { [native code] }",
    "presentation−[object Presentation]",
    "serial−[object Serial]",
    "locks−[object LockManager]",
    "requestMIDIAccess−function requestMIDIAccess() { [native code] }",
    "locks−[object LockManager]",
    "requestMediaKeySystemAccess−function requestMediaKeySystemAccess() { [native code] }",
    "vendor−Google Inc.",
    "pdfViewerEnabled−true",
    "language−en-US",
    "setAppBadge−function setAppBadge() { [native code] }",
    "geolocation−[object Geolocation]",
    "userAgentData−[object NavigatorUAData]",
    "mediaCapabilities−[object MediaCapabilities]",
    "requestMIDIAccess−function requestMIDIAccess() { [native code] }",
    "getUserMedia−function getUserMedia() { [native code] }",
    "mediaDevices−[object MediaDevices]",
    "webkitPersistentStorage−[object DeprecatedStorageQuota]",
    "sendBeacon−function sendBeacon() { [native code] }",
    "hardwareConcurrency−32",
    "credentials−[object CredentialsContainer]",
    "storage−[object StorageManager]",
    "cookieEnabled−true",
    "pdfViewerEnabled−true",
    "windowControlsOverlay−[object WindowControlsOverlay]",
    "scheduling−[object Scheduling]",
    "pdfViewerEnabled−true",
    "hardwareConcurrency−32",
    "xr−[object XRSystem]",
    "webdriver−false",
    "getInstalledRelatedApps−function getInstalledRelatedApps() { [native code] }",
    "getInstalledRelatedApps−function getInstalledRelatedApps() { [native code] }",
    "bluetooth−[object Bluetooth]"
]
document_key = ['_reactListeningo743lnnpvdg', 'location']
window_key = [
    "0",
    "window",
    "self",
    "document",
    "name",
    "location",
    "customElements",
    "history",
    "navigation",
    "locationbar",
    "menubar",
    "personalbar",
    "scrollbars",
    "statusbar",
    "toolbar",
    "status",
    "closed",
    "frames",
    "length",
    "top",
    "opener",
    "parent",
    "frameElement",
    "navigator",
    "origin",
    "external",
    "screen",
    "innerWidth",
    "innerHeight",
    "scrollX",
    "pageXOffset",
    "scrollY",
    "pageYOffset",
    "visualViewport",
    "screenX",
    "screenY",
    "outerWidth",
    "outerHeight",
    "devicePixelRatio",
    "clientInformation",
    "screenLeft",
    "screenTop",
    "styleMedia",
    "onsearch",
    "isSecureContext",
    "trustedTypes",
    "performance",
    "onappinstalled",
    "onbeforeinstallprompt",
    "crypto",
    "indexedDB",
    "sessionStorage",
    "localStorage",
    "onbeforexrselect",
    "onabort",
    "onbeforeinput",
    "onbeforematch",
    "onbeforetoggle",
    "onblur",
    "oncancel",
    "oncanplay",
    "oncanplaythrough",
    "onchange",
    "onclick",
    "onclose",
    "oncontentvisibilityautostatechange",
    "oncontextlost",
    "oncontextmenu",
    "oncontextrestored",
    "oncuechange",
    "ondblclick",
    "ondrag",
    "ondragend",
    "ondragenter",
    "ondragleave",
    "ondragover",
    "ondragstart",
    "ondrop",
    "ondurationchange",
    "onemptied",
    "onended",
    "onerror",
    "onfocus",
    "onformdata",
    "oninput",
    "oninvalid",
    "onkeydown",
    "onkeypress",
    "onkeyup",
    "onload",
    "onloadeddata",
    "onloadedmetadata",
    "onloadstart",
    "onmousedown",
    "onmouseenter",
    "onmouseleave",
    "onmousemove",
    "onmouseout",
    "onmouseover",
    "onmouseup",
    "onmousewheel",
    "onpause",
    "onplay",
    "onplaying",
    "onprogress",
    "onratechange",
    "onreset",
    "onresize",
    "onscroll",
    "onsecuritypolicyviolation",
    "onseeked",
    "onseeking",
    "onselect",
    "onslotchange",
    "onstalled",
    "onsubmit",
    "onsuspend",
    "ontimeupdate",
    "ontoggle",
    "onvolumechange",
    "onwaiting",
    "onwebkitanimationend",
    "onwebkitanimationiteration",
    "onwebkitanimationstart",
    "onwebkittransitionend",
    "onwheel",
    "onauxclick",
    "ongotpointercapture",
    "onlostpointercapture",
    "onpointerdown",
    "onpointermove",
    "onpointerrawupdate",
    "onpointerup",
    "onpointercancel",
    "onpointerover",
    "onpointerout",
    "onpointerenter",
    "onpointerleave",
    "onselectstart",
    "onselectionchange",
    "onanimationend",
    "onanimationiteration",
    "onanimationstart",
    "ontransitionrun",
    "ontransitionstart",
    "ontransitionend",
    "ontransitioncancel",
    "onafterprint",
    "onbeforeprint",
    "onbeforeunload",
    "onhashchange",
    "onlanguagechange",
    "onmessage",
    "onmessageerror",
    "onoffline",
    "ononline",
    "onpagehide",
    "onpageshow",
    "onpopstate",
    "onrejectionhandled",
    "onstorage",
    "onunhandledrejection",
    "onunload",
    "crossOriginIsolated",
    "scheduler",
    "alert",
    "atob",
    "blur",
    "btoa",
    "cancelAnimationFrame",
    "cancelIdleCallback",
    "captureEvents",
    "clearInterval",
    "clearTimeout",
    "close",
    "confirm",
    "createImageBitmap",
    "fetch",
    "find",
    "focus",
    "getComputedStyle",
    "getSelection",
    "matchMedia",
    "moveBy",
    "moveTo",
    "open",
    "postMessage",
    "print",
    "prompt",
    "queueMicrotask",
    "releaseEvents",
    "reportError",
    "requestAnimationFrame",
    "requestIdleCallback",
    "resizeBy",
    "resizeTo",
    "scroll",
    "scrollBy",
    "scrollTo",
    "setInterval",
    "setTimeout",
    "stop",
    "structuredClone",
    "webkitCancelAnimationFrame",
    "webkitRequestAnimationFrame",
    "chrome",
    "caches",
    "cookieStore",
    "ondevicemotion",
    "ondeviceorientation",
    "ondeviceorientationabsolute",
    "launchQueue",
    "documentPictureInPicture",
    "getScreenDetails",
    "queryLocalFonts",
    "showDirectoryPicker",
    "showOpenFilePicker",
    "showSaveFilePicker",
    "originAgentCluster",
    "onpageswap",
    "onpagereveal",
    "credentialless",
    "speechSynthesis",
    "onscrollend",
    "webkitRequestFileSystem",
    "webkitResolveLocalFileSystemURL",
    "sendMsgToSolverCS",
    "webpackChunk_N_E",
    "__next_set_public_path__",
    "next",
    "__NEXT_DATA__",
    "__SSG_MANIFEST_CB",
    "__NEXT_P",
    "_N_E",
    "regeneratorRuntime",
    "__REACT_INTL_CONTEXT__",
    "DD_RUM",
    "_",
    "filterCSS",
    "filterXSS",
    "__SEGMENT_INSPECTOR__",
    "__NEXT_PRELOADREADY",
    "Intercom",
    "__MIDDLEWARE_MATCHERS",
    "__STATSIG_SDK__",
    "__STATSIG_JS_SDK__",
    "__STATSIG_RERENDER_OVERRIDE__",
    "_oaiHandleSessionExpired",
    "__BUILD_MANIFEST",
    "__SSG_MANIFEST",
    "__intercomAssignLocation",
    "__intercomReloadLocation"
]


class ScriptSrcParser(HTMLParser):
    def handle_starttag(self, tag, attrs):
        global cached_scripts, cached_dpl, cached_time
        if tag == "script":
            attrs_dict = dict(attrs)
            if "src" in attrs_dict:
                src = attrs_dict["src"]
                cached_scripts.append(src)
                match = re.search(r"c/[^/]*/_", src)
                if match:
                    cached_dpl = match.group(0)
                    cached_time = int(time.time())


def get_data_build_from_html(html_content):
    global cached_scripts, cached_dpl, cached_time
    parser = ScriptSrcParser()
    parser.feed(html_content)
    if not cached_scripts:
        cached_scripts.append("https://chatgpt.com/backend-api/sentinel/sdk.js")
    if not cached_dpl:
        match = re.search(r'<html[^>]*data-build="([^"]*)"', html_content)
        if match:
            data_build = match.group(1)
            cached_dpl = data_build
            cached_time = int(time.time())
            logger.info(f"Found dpl: {cached_dpl}")


async def get_dpl(service):
    global cached_scripts, cached_dpl, cached_time
    if int(time.time()) - cached_time < 15 * 60:
        return True
    headers = service.base_headers.copy()
    # T4: 首页 GET 用 HTML Accept（真实浏览器导航请求）
    headers["accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    headers["sec-fetch-dest"] = "document"
    headers["sec-fetch-mode"] = "navigate"
    headers["sec-fetch-site"] = "none"
    headers["sec-fetch-user"] = "?1"
    cached_scripts = []
    cached_dpl = ""
    try:
        if conversation_only:
            return True
        r = await service.s.get(f"{service.host_url}/", headers=headers, timeout=5)
        r.raise_for_status()
        get_data_build_from_html(r.text)
        if not cached_dpl:
            raise Exception("No Cached DPL")
        else:
            return True
    except Exception as e:
        logger.info(f"Failed to get dpl: {e}")
        cached_dpl = None
        cached_time = int(time.time())
        return False


def get_parse_time(tz_offset_min=None, tz_name=None):
    """支持 antiban 动态覆盖时区，默认沿用全局配置。"""
    offset = tz_offset_min if tz_offset_min is not None else client_timezone_offset_min
    name = tz_name if tz_name else client_timezone
    now = datetime.now(timezone(timedelta(minutes=offset)))
    offset_hours = int(offset / 60)
    offset_label = f"GMT{offset_hours:+03d}00"
    timezone_name = name.split("/")[-1].replace("_", " ")
    return now.strftime(timeLayout) + f" {offset_label} ({timezone_name})"


@cache.memoize(expire=3600 * 24 * 7)
def _get_static_config_meta(req_token):
    """Token 级缓存：仅缓存稳定的静态 metadata，避免每次重读 fp_map。

    动态字段（time / perf_counter / uuid / 随机 navigator key）NOT cached，每次重算。
    旧实现把整个 config 缓存了 7 天，导致同一 token 多次 PoW 输入完全一致 → 重放特征。
    """
    screen_sum = None
    cores_val = None
    page_load_ms = None
    try:
        from utils import configs as _configs
        if _configs.enable_antiban and req_token:
            from utils.antiban import fingerprint as _fp
            screen_sum = _fp.get_screen_resolution_sum(req_token)
            cores_val = _fp.get_hardware_concurrency(req_token)
            page_load_ms = _fp.get_virtual_page_load_ms(req_token)
    except Exception:
        pass
    return {"screen_sum": screen_sum, "cores": cores_val, "page_load_ms": page_load_ms}


def get_config(user_agent, req_token=None, tz_offset_min=None, tz_name=None):
    """生成 PoW config。静态字段 token 级缓存；动态字段（时间/UUID/随机 key）每次重算。"""
    meta = _get_static_config_meta(req_token)
    screen_sum = meta.get("screen_sum")
    cores_val = meta.get("cores")
    page_load_ms = meta.get("page_load_ms")

    # perf_counter：真实浏览器从 page load 起算（秒级到分钟级），不是进程级累加
    now_perf_ms = time.perf_counter() * 1000
    if page_load_ms is not None:
        # 用 token 级稳定的"虚拟页面加载偏移"：模拟用户已在页面停留若干秒
        perf_relative = now_perf_ms - page_load_ms
    else:
        perf_relative = now_perf_ms

    # T6: navigator_key 池含 "hardwareConcurrency−32" 等硬编码键；
    # 若随机选中这类与 fp.hardware_concurrency 不一致的字符串，会暴露指纹矛盾。
    # 优先选不含数值的键（vendor/cookieEnabled 等），仅当抽中 hardwareConcurrency-* 时改写为真实值。
    chosen_nav_key = random.choice(navigator_key)
    if cores_val is not None and chosen_nav_key.startswith("hardwareConcurrency−"):
        chosen_nav_key = f"hardwareConcurrency−{cores_val}"

    config = [
        screen_sum if screen_sum is not None else random.choice([1920 + 1080, 2560 + 1440, 1920 + 1200, 2560 + 1600]),
        get_parse_time(tz_offset_min, tz_name),
        4294705152,
        0,
        user_agent,
        random.choice(cached_scripts) if cached_scripts else "",
        cached_dpl,
        oai_language,
        accept_language,
        0,
        chosen_nav_key,
        random.choice(document_key),
        random.choice(window_key),
        perf_relative,
        str(uuid.uuid4()),
        "",
        cores_val if cores_val is not None else random.choice(cores),
        time.time() * 1000 - now_perf_ms,
    ]
    return config


def get_answer_token(seed, diff, config):
    start = time.time()
    answer, solved = generate_answer(seed, diff, config)
    end = time.time()
    logger.info(f'diff: {diff}, time: {int((end - start) * 1e6) / 1e3}ms, solved: {solved}')
    return "gAAAAAB" + answer, solved


def generate_answer(seed, diff, config):
    diff_len = len(diff)
    seed_encoded = seed.encode()
    static_config_part1 = (json.dumps(config[:3], separators=(',', ':'), ensure_ascii=False)[:-1] + ',').encode()
    static_config_part2 = (',' + json.dumps(config[4:9], separators=(',', ':'), ensure_ascii=False)[1:-1] + ',').encode()
    static_config_part3 = (',' + json.dumps(config[10:], separators=(',', ':'), ensure_ascii=False)[1:]).encode()

    target_diff = bytes.fromhex(diff)

    for i in range(500000):
        dynamic_json_i = str(i).encode()
        dynamic_json_j = str(i >> 1).encode()
        final_json_bytes = static_config_part1 + dynamic_json_i + static_config_part2 + dynamic_json_j + static_config_part3
        base_encode = pybase64.b64encode(final_json_bytes)
        hash_value = hashlib.sha3_512(seed_encoded + base_encode).digest()
        if hash_value[:diff_len] <= target_diff:
            return base_encode.decode(), True

    return "wQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D" + pybase64.b64encode(f'"{seed}"'.encode()).decode(), False


def get_requirements_token(config):
    require, solved = generate_answer(format(random.random()), "0fffff", config)
    return 'gAAAAAC' + require


if __name__ == "__main__":
    # cached_scripts.append(
    #     "https://cdn.oaistatic.com/_next/static/cXh69klOLzS0Gy2joLDRS/_ssgManifest.js?dpl=453ebaec0d44c2decab71692e1bfe39be35a24b3")
    # cached_dpl = "453ebaec0d44c2decab71692e1bfe39be35a24b3"
    # cached_time = int(time.time())
    # for i in range(10):
    #     seed = format(random.random())
    #     diff = "000032"
    #     config = get_config("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome")
    #     answer = get_answer_token(seed, diff, config)
    cached_scripts.append(
        "https://cdn.oaistatic.com/_next/static/cXh69klOLzS0Gy2joLDRS/_ssgManifest.js?dpl=453ebaec0d44c2decab71692e1bfe39be35a24b3")
    cached_dpl = "prod-f501fe933b3edf57aea882da888e1a544df99840"
    config = get_config("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")
    get_requirements_token(config)
