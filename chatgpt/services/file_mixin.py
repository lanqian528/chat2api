"""文件上传/下载操作 Mixin。

封装与 ChatGPT /files 与 /conversation 文件相关的 8 个端点：
- 上传：get_upload_url → upload → check_upload → get_download_url_from_upload
- 下载：get_download_url / get_attachment_url / get_response_file_url
- 高层入口：upload_file（图片尺寸探测、扩展名/用途推断）

原始位置：chatgpt/ChatService.py:580-728
"""

import asyncio
import uuid

from fastapi import HTTPException

from api.files import get_image_size, get_file_extension, determine_file_use_case
from utils.configs import client_timezone_offset_min
from utils.Logger import logger


class FileMixin:
    async def get_download_url(self, file_id):
        url = f"{self.base_url}/files/{file_id}/download"
        headers = self.base_headers.copy()
        try:
            r = await self.s.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                download_url = r.json().get('download_url')
                return download_url
            else:
                raise HTTPException(status_code=r.status_code, detail=r.text)
        except Exception as e:
            logger.error(f"Failed to get download url: {e}")
            return ""

    async def get_attachment_url(self, file_id, conversation_id):
        url = f"{self.base_url}/conversation/{conversation_id}/attachment/{file_id}/download"
        headers = self.base_headers.copy()
        try:
            r = await self.s.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                download_url = r.json().get('download_url')
                return download_url
            else:
                raise HTTPException(status_code=r.status_code, detail=r.text)
        except Exception as e:
            logger.error(f"Failed to get download url: {e}")
            return ""

    async def get_download_url_from_upload(self, file_id):
        url = f"{self.base_url}/files/{file_id}/uploaded"
        headers = self.base_headers.copy()
        try:
            r = await self.s.post(url, headers=headers, json={}, timeout=10)
            if r.status_code == 200:
                download_url = r.json().get('download_url')
                return download_url
            else:
                raise HTTPException(status_code=r.status_code, detail=r.text)
        except Exception as e:
            logger.error(f"Failed to get download url from upload: {e}")
            return ""

    async def get_upload_url(self, file_name, file_size, use_case="multimodal"):
        url = f'{self.base_url}/files'
        headers = self.base_headers.copy()
        try:
            r = await self.s.post(
                url,
                headers=headers,
                json={"file_name": file_name, "file_size": file_size, "reset_rate_limits": False, "timezone_offset_min": client_timezone_offset_min, "use_case": use_case},
                timeout=5,
            )
            if r.status_code == 200:
                res = r.json()
                file_id = res.get('file_id')
                upload_url = res.get('upload_url')
                logger.info(f"file_id: {file_id}, upload_url: {upload_url}")
                return file_id, upload_url
            else:
                raise HTTPException(status_code=r.status_code, detail=r.text)
        except Exception as e:
            logger.error(f"Failed to get upload url: {e}")
            return "", ""

    async def upload(self, upload_url, file_content, mime_type):
        headers = self.base_headers.copy()
        headers.update(
            {
                'accept': 'application/json, text/plain, */*',
                'content-type': mime_type,
                'x-ms-blob-type': 'BlockBlob',
                'x-ms-version': '2020-04-08',
            }
        )
        headers.pop('authorization', None)
        headers.pop('oai-device-id', None)
        headers.pop('oai-language', None)
        try:
            r = await self.s.put(upload_url, headers=headers, data=file_content, timeout=60)
            if r.status_code == 201:
                return True
            else:
                raise HTTPException(status_code=r.status_code, detail=r.text)
        except Exception as e:
            logger.error(f"Failed to upload file: {e}")
            return False

    async def upload_file(self, file_content, mime_type):
        if not file_content or not mime_type:
            return None

        width, height = None, None
        if mime_type.startswith("image/"):
            try:
                width, height = await get_image_size(file_content)
            except Exception as e:
                logger.error(f"Error image mime_type, change to text/plain: {e}")
                mime_type = 'text/plain'
        file_size = len(file_content)
        file_extension = await get_file_extension(mime_type)
        file_name = f"{uuid.uuid4()}{file_extension}"
        use_case = await determine_file_use_case(mime_type)

        file_id, upload_url = await self.get_upload_url(file_name, file_size, use_case)
        if file_id and upload_url:
            if await self.upload(upload_url, file_content, mime_type):
                download_url = await self.get_download_url_from_upload(file_id)
                if download_url:
                    file_meta = {
                        "file_id": file_id,
                        "file_name": file_name,
                        "size_bytes": file_size,
                        "mime_type": mime_type,
                        "width": width,
                        "height": height,
                        "use_case": use_case,
                    }
                    logger.info(f"File_meta: {file_meta}")
                    return file_meta

    async def check_upload(self, file_id):
        url = f'{self.base_url}/files/{file_id}'
        headers = self.base_headers.copy()
        try:
            for i in range(30):
                r = await self.s.get(url, headers=headers, timeout=5)
                if r.status_code == 200:
                    res = r.json()
                    retrieval_index_status = res.get('retrieval_index_status', '')
                    if retrieval_index_status == "success":
                        break
                await asyncio.sleep(1)
            return True
        except HTTPException:
            return False

    async def get_response_file_url(self, conversation_id, message_id, sandbox_path):
        try:
            url = f"{self.base_url}/conversation/{conversation_id}/interpreter/download"
            params = {"message_id": message_id, "sandbox_path": sandbox_path}
            headers = self.base_headers.copy()
            r = await self.s.get(url, headers=headers, params=params, timeout=10)
            if r.status_code == 200:
                return r.json().get("download_url")
            else:
                return None
        except Exception:
            logger.info("Failed to get response file url")
            return None
