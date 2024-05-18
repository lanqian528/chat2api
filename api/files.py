import io

import pybase64
from PIL import Image

from utils.Client import Client


async def get_file_content(url):
    if url.startswith("data:"):
        mime_type, base64_data = url.split(';')[0].split(':')[1], url.split(',')[1]
        file_content = pybase64.b64decode(base64_data)
        return file_content, mime_type
    else:
        client = Client()
        try:
            r = await client.get(url)
            r.raise_for_status()
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
        "application/x-latext": ".latex",
        "text/markdown": ".md",
        "text/plain": ".txt",
        "text/x-ruby": ".rb",
        "text/x-script.python": ".py",
        # 其他 MIME 类型和扩展名...
    }
    return extension_mapping.get(mime_type, "")
