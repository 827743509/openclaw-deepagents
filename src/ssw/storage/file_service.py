"""文件存储高层封装。

业务代码统一通过 FileService 操作文件，不直接调 OssClient，便于以后切换存储后端
（本地磁盘、S3 等）时只改这一层。
"""
from ssw.core.logging import get_logger
from ssw.storage.oss_client import OssClient, get_oss_client

logger = get_logger(__name__)


class FileService:
    def __init__(self, oss: OssClient | None = None) -> None:
        self._oss = oss or get_oss_client()

    @property
    def bucket(self) -> str:
        return self._oss.bucket

    @staticmethod
    def build_object_key(file_hash: str, suffix: str) -> str:
        # 用 file_hash 作为 key 天然幂等：同文件多次上传命中同一 object
        return f"documents/{file_hash}{suffix}"

    async def upload(self, *, content: bytes, file_hash: str, suffix: str, mime_type: str) -> str:
        key = self.build_object_key(file_hash, suffix)
        await self._oss.put_object(key=key, body=content, content_type=mime_type)
        return key

    async def download(self, object_key: str) -> bytes:
        return await self._oss.get_object(object_key)

    async def delete(self, object_key: str) -> None:
        """删除存储中的 object。
        """
        await self._oss.delete_object(object_key)



def get_file_service() -> FileService:
    return FileService()
