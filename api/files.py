import io

import pybase64
from PIL import Image

from utils.Client import Client
from utils.config import export_proxy_url, cf_file_url


async def get_file_content(url):
    if url.startswith("data:"):
        mime_type, base64_data = url.split(';')[0].split(':')[1], url.split(',')[1]
        file_content = pybase64.b64decode(base64_data)
        return file_content, mime_type
    else:
        client = Client()
        try:
            if cf_file_url:
                body = {"file_url": url}
                r = await client.post(cf_file_url, timeout=60, json=body)
            else:
                r = await client.get(url, proxy=export_proxy_url, timeout=60)
            if r.status_code != 200:
                return None, None
            file_content = r.content
            mime_type = r.headers.get('Content-Type', '').split(';')[0].strip()
            return file_content, mime_type
        finally:
            await client.close()
            del client


async def determine_file_use_case(mime_type):
    multimodal_types = ["image/jpeg", "image/webp", "image/png", "image/gif"]
    my_files_types = ["text/x-php", "application/msword", "text/x-c", "text/html",
                      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                      "application/json", "text/javascript", "application/pdf",
                      "text/x-java", "text/x-tex", "text/x-typescript", "text/x-sh",
                      "text/x-csharp", "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                      "text/x-c++", "application/x-latext", "text/markdown", "text/plain",
                      "text/x-ruby", "text/x-script.python"]

    if mime_type in multimodal_types:
        return "multimodal"
    elif mime_type in my_files_types:
        return "my_files"
    else:
        return "ace_upload"


async def get_image_size(file_content):
    with Image.open(io.BytesIO(file_content)) as img:
        return img.width, img.height


async def get_file_extension(mime_type):
    extension_mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "text/x-php": ".php",
        "application/msword": ".doc",
        "text/x-c": ".c",
        "text/html": ".html",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/json": ".json",
        "text/javascript": ".js",
        "application/pdf": ".pdf",
        "text/x-java": ".java",
        "text/x-tex": ".tex",
        "text/x-typescript": ".ts",
        "text/x-sh": ".sh",
        "text/x-csharp": ".cs",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "text/x-c++": ".cpp",
        "application/x-latex": ".latex",
        "text/markdown": ".md",
        "text/plain": ".txt",
        "text/x-ruby": ".rb",
        "text/x-script.python": ".py",
        "application/zip": ".zip",
        "application/x-zip-compressed": ".zip",
        "application/x-tar": ".tar",
        "application/x-compressed-tar": ".tar.gz",
        "application/vnd.rar": ".rar",
        "application/x-rar-compressed": ".rar",
        "application/x-7z-compressed": ".7z",
        "application/octet-stream": ".bin",
        "audio/mpeg": ".mp3",
        "audio/wav": ".wav",
        "audio/ogg": ".ogg",
        "audio/aac": ".aac",
        "video/mp4": ".mp4",
        "video/x-msvideo": ".avi",
        "video/x-matroska": ".mkv",
        "video/webm": ".webm",
        "application/rtf": ".rtf",
        "application/vnd.ms-excel": ".xls",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "text/css": ".css",
        "text/xml": ".xml",
        "application/xml": ".xml",
        "application/vnd.android.package-archive": ".apk",
        "application/vnd.apple.installer+xml": ".mpkg",
        "application/x-bzip": ".bz",
        "application/x-bzip2": ".bz2",
        "application/x-csh": ".csh",
        "application/x-debian-package": ".deb",
        "application/x-dvi": ".dvi",
        "application/java-archive": ".jar",
        "application/x-java-jnlp-file": ".jnlp",
        "application/vnd.mozilla.xul+xml": ".xul",
        "application/vnd.ms-fontobject": ".eot",
        "application/ogg": ".ogx",
        "application/x-font-ttf": ".ttf",
        "application/font-woff": ".woff",
        "application/x-shockwave-flash": ".swf",
        "application/vnd.visio": ".vsd",
        "application/xhtml+xml": ".xhtml",
        "application/vnd.ms-powerpoint": ".ppt",
        "application/vnd.oasis.opendocument.text": ".odt",
        "application/vnd.oasis.opendocument.spreadsheet": ".ods",
        "application/x-xpinstall": ".xpi",
        "application/vnd.google-earth.kml+xml": ".kml",
        "application/vnd.google-earth.kmz": ".kmz",
        "application/x-font-otf": ".otf",
        "application/vnd.ms-excel.addin.macroEnabled.12": ".xlam",
        "application/vnd.ms-excel.sheet.binary.macroEnabled.12": ".xlsb",
        "application/vnd.ms-excel.template.macroEnabled.12": ".xltm",
        "application/vnd.ms-powerpoint.addin.macroEnabled.12": ".ppam",
        "application/vnd.ms-powerpoint.presentation.macroEnabled.12": ".pptm",
        "application/vnd.ms-powerpoint.slideshow.macroEnabled.12": ".ppsm",
        "application/vnd.ms-powerpoint.template.macroEnabled.12": ".potm",
        "application/vnd.ms-word.document.macroEnabled.12": ".docm",
        "application/vnd.ms-word.template.macroEnabled.12": ".dotm",
        "application/x-ms-application": ".application",
        "application/x-ms-wmd": ".wmd",
        "application/x-ms-wmz": ".wmz",
        "application/x-ms-xbap": ".xbap",
        "application/vnd.ms-xpsdocument": ".xps",
        "application/x-silverlight-app": ".xap"
    }
    return extension_mapping.get(mime_type, "")
