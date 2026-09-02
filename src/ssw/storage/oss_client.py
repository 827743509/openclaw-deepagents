"""腾讯云 COS 客户端封装。

cos-python-sdk-v5 是同步 SDK；本项目要求 IO 一律 async，所以用 asyncio.to_thread
把阻塞调用包成协程。后续章节再扩展 upload/download/get_url 等方法。
"""

import asyncio
from typing import BinaryIO

from minio import Minio

from ssw.config import OSS_BUCKET, OSS_ORIGINS, OSS_ACCESS_KEY, OSS_SECRET_KEY
from ssw.core.logging import get_logger

logger = get_logger(__name__)


class OssClient:
    """腾讯云 COS 客户端单例封装。"""

    def __init__(self) -> None:

        self._client = Minio(
            endpoint=OSS_ORIGINS,
            access_key=OSS_ACCESS_KEY,
            secret_key=OSS_SECRET_KEY,
            secure=False,  # HTTP=False，HTTPS=True
        )
        self._bucket = OSS_BUCKET

    @property
    def bucket(self) -> str:
        return self._bucket

    async def put_object(self, *, key: str, body: BinaryIO,length: int, content_type: str) -> None:
        """上传字节流到指定 object key。同名覆盖。"""
        await asyncio.to_thread(
            self._client.put_object,
            bucket_name=self._bucket,
            object_name=key,
            data=body,
            content_type=content_type,
            length=length,
        )

    async def get_object(self, key: str) -> bytes:
        """读取 object 全部字节。"""

        def _read() -> bytes:
            response = self._client.get_object(bucket_name=self._bucket, object_name=key)
            # SDK 返回的 Body 是流式对象，get_raw_stream 拿到原始 stream
            return response.read()

        return await asyncio.to_thread(_read)

    async def delete_object(self, key: str) -> None:
        """删除指定 object。。"""
        await asyncio.to_thread(
            self._client.remove_object, bucket_name=self._bucket, object_name=key
        )


_oss_client: OssClient | None = None


def get_oss_client() -> OssClient:
    """惰性构造：未配置时直接抛 ConfigurationError，由全局错误处理器转 503。"""
    global _oss_client
    if _oss_client is None:
        _oss_client = OssClient()
    return _oss_client
