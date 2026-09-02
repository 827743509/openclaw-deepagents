import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePath
from uuid import UUID

from fastapi import UploadFile
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ssw.config import UPLOAD_MAX_SIZE_MB
from ssw.core.exceptions import NotFoundError
from ssw.core.logging import get_logger
from ssw.db.models import DocumentStatus, DocumentChunk, Document, IngestionTaskType, IngestionTask
from ssw.ingestion.tasks import ingest_document_task, reindex_document_task
from ssw.repository.chunk_repo import DocumentChunkRepository, ChunkStats
from ssw.repository.document_repo import DocumentRepository
from ssw.repository.ingestion_task_repo import IngestionTaskRepository
from ssw.storage.file_service import get_file_service, FileService

logger = get_logger(__name__)

# 受支持的 MIME 类型。Docling 还支持其他格式，本章先收敛为常见四种以便课件演示
_ACCEPTED_MIME_TYPES: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/markdown": ".md",
    "text/x-markdown": ".md",
    "text/html": ".html",
    "application/xhtml+xml": ".html",
}

_ACCEPTED_SUFFIXES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
}
# 删除允许的状态：终态 + uploading（uploading 时后台任务还没真正写 chunks）
_DELETABLE_STATUSES = frozenset(
    {DocumentStatus.READY, DocumentStatus.FAILED, DocumentStatus.UPLOADING}
)
@dataclass(frozen=True)
class KnowledgeBaseStats:
    """知识库整体规模快照，按调用者权限范围统计。

    chunk_count 仅计入 status='ready' 的文档，与检索可见性一致；
    last_indexed_at 取最近一次 ready 文档的 updated_at（含 reindex 后的刷新）。
    """

    document_count: int
    chunk_count: int
    last_indexed_at: datetime | None

def _resolve_mime_and_suffix(file: UploadFile) -> tuple[str, str]:
    """根据 UploadFile 的 content_type 和扩展名共同判定。

    浏览器上传 .md 时常给 application/octet-stream，所以扩展名优先级更高。
    """
    suffix = PurePath(file.filename or "").suffix.lower()
    if suffix in _ACCEPTED_SUFFIXES:
        return _ACCEPTED_SUFFIXES[suffix], suffix

    mime = file.content_type or ""
    if mime in _ACCEPTED_MIME_TYPES:
        return mime, _ACCEPTED_MIME_TYPES[mime]

    raise ValidationError(
        f"不支持的文件类型：{file.filename}（{mime or '未知'}）。"
        "当前仅支持 PDF、DOCX、Markdown、HTML"
    )

class DocumentService:
    def __init__(self, session: AsyncSession, repo: DocumentRepository,chunk_repo:DocumentChunkRepository,task_repo:IngestionTaskRepository,file_service: FileService | None = None) -> None:
        self.session=session
        self.repo = repo
        self.chunk_repo = chunk_repo
        self.task_repo=task_repo
        self.file_service = file_service or get_file_service()

    async def upload(
        self,
        file: UploadFile,
        created_by: UUID | None = None,
    ) -> Document:
        mime_type, suffix = _resolve_mime_and_suffix(file)

        content = await file.read()
        max_bytes = UPLOAD_MAX_SIZE_MB * 1024 * 1024
        if len(content) == 0:
            raise ValidationError("上传文件为空")
        if len(content) > max_bytes:
            raise ValidationError(f"文件超过 {UPLOAD_MAX_SIZE_MB} MB 上限")

        file_hash = hashlib.sha256(content).hexdigest()

        existing = await self.repo.get_by_hash(file_hash)
        if existing is not None:
            # 命中幂等：直接复用现有记录，不重复入库
            logger.info("file_hash hit, reuse document: %s", existing.id)
            return existing

        object_key = await self.file_service.upload(
            content=content,
            file_hash=file_hash,
            suffix=suffix,
            mime_type=mime_type,
        )

        document = Document(
            name=file.filename or f"{file_hash}{suffix}",
            file_hash=file_hash,
            mime_type=mime_type,
            size=len(content),
            oss_bucket=self.file_service.bucket,
            oss_object_key=object_key,
            status=DocumentStatus.UPLOADING,
            created_by=created_by,
        )
        await self.repo.add(document)
        task = await self.task_repo.create(document.id, IngestionTaskType.INGEST)
        await self.session.commit()
        await self.session.refresh(document)

        # commit 之后 Celery worker 用独立 session 才能查到刚落库的 document / task
        ingest_document_task.delay(str(document.id), str(task.id))

        return document

    async def get(
        self,
        document_id: UUID
    ) -> Document:
        doc = await self.repo.get_by_id(document_id)
        if doc is None:
            raise NotFoundError("文档不存在")
        return doc

    async def list_documents(
        self,
        page: int,
        page_size: int,
        *,
        status: DocumentStatus | None = None,
    ) -> tuple[list[Document], int]:
        return await self.repo.list_paginated(
            page, page_size, status=status
        )

    async def delete(self, document_id: UUID) -> None:
        """删除文档。

        DB 是真相之源：先删 DB 行再删 COS object，COS 删除失败仅打 warning，
        避免出现"DB 还在 / 用户以为删了"的更糟状态。
        """
        doc = await self.repo.get_by_id(document_id)
        if doc is None:
            raise NotFoundError("文档不存在")

        if doc.status not in _DELETABLE_STATUSES:
            raise ValidationError("文档处理中，请等待完成或失败后再删除")

        object_key = doc.cos_object_key
        await self.repo.delete(doc)
        await self.session.commit()

        await self.file_service.delete(object_key)
        logger.info("document deleted: id=%s", document_id)

    async def retry(self, document_id: UUID) -> Document:
        """从 failed 重新触发 ingest。"""
        doc = await self.repo.get_by_id(document_id)
        if doc is None:
            raise NotFoundError("文档不存在")
        if doc.status != DocumentStatus.FAILED:
            raise ValidationError("仅失败状态的文档支持重试")

        # 防御性清场：理论上 failed 文档不会有 chunks，但写 chunks 阶段失败时可能残留
        await self.chunk_repo.delete_by_document(document_id)
        doc.status = DocumentStatus.UPLOADING
        doc.error_message = None
        task = await self.task_repo.create(doc.id, IngestionTaskType.INGEST)
        await self.session.commit()
        await self.session.refresh(doc)

        ingest_document_task.delay(str(doc.id), str(task.id))
        logger.info("document retry scheduled: id=%s", document_id)
        return doc

    async def reindex(
        self,
        document_id: UUID,
        file: UploadFile,
    ) -> Document:
        """用新文件替换原文档并触发增量重建。

        - 只允许 READY / FAILED 状态触发，避免与正在进行的 ingest 抢资源
        - 文件 MIME 必须与原文档一致：避免「PDF 文档被 Markdown 覆盖」造成的
          预览 / 下载链路状态混乱
        - 新文件覆盖到 COS 的同一个 object_key，version+1 由 worker 在 reindex
          成功后才提交，避免失败的话用户列表里看到版本号但内容没变
        """
        doc = await self.repo.get_by_id(document_id)
        if doc is None:
            raise NotFoundError("文档不存在")
        if doc.status not in {DocumentStatus.READY, DocumentStatus.FAILED}:
            raise ValidationError("文档处理中，请等待完成或失败后再重新索引")

        mime_type, suffix = _resolve_mime_and_suffix(file)
        if mime_type != doc.mime_type:
            raise ValidationError(
                f"新版本文件类型必须与原文档一致（当前为 {doc.mime_type}）"
            )

        content = await file.read()
        max_bytes = UPLOAD_MAX_SIZE_MB * 1024 * 1024
        if len(content) == 0:
            raise ValidationError("上传文件为空")
        if len(content) > max_bytes:
            raise ValidationError(f"文件超过 {UPLOAD_MAX_SIZE_MB} MB 上限")

        new_hash = hashlib.sha256(content).hexdigest()
        if new_hash == doc.file_hash:
            # 内容完全一致没有重建必要，避免重复上传相同内容浪费 embedding 配额
            raise ValidationError("文件内容与现有版本一致，无需重新索引")

        # 把新文件覆盖到同一个 object key：reindex 失败时 worker 不动版本号，
        # 但 COS 已经是新内容——这是教学项目可接受的取舍（避免引入文件版本表）
        new_object_key = await self.file_service.upload(
            content=content,
            file_hash=new_hash,
            suffix=suffix,
            mime_type=mime_type,
        )

        doc.file_hash = new_hash
        doc.size = len(content)
        doc.cos_object_key = new_object_key
        doc.cos_bucket = self.file_service.bucket
        doc.cos_region = self.file_service.region
        doc.status = DocumentStatus.PARSING
        doc.error_message = None
        if file.filename:
            doc.name = file.filename

        task = await self.task_repo.create(doc.id, IngestionTaskType.REINDEX)
        await self.session.commit()
        await self.session.refresh(doc)

        reindex_document_task.delay(str(doc.id), str(task.id))
        logger.info("document reindex scheduled: id=%s", document_id)
        return doc

    async def get_latest_task(self, document_id: UUID) -> IngestionTask | None:
        return await self.task_repo.get_latest_by_document(document_id)



    async def list_chunks(
        self,
        document_id: UUID,
        page: int,
        page_size: int
    ) -> tuple[list[DocumentChunk], int, ChunkStats | None]:
        # 先确保 document 存在 + 当前用户可见
        await self.get(document_id)
        items, total = await self.chunk_repo.list_paginated_by_document(
            document_id, page, page_size
        )
        stats = await self.chunk_repo.get_stats(document_id)
        return items, total, stats

    async def get_stats(
        self,
        *,
        permission_tags: list[str] | None = None,
    ) -> KnowledgeBaseStats:
        """聚合 documents / chunks 总数与最新入库时间。

        permission_tags：admin 视角传 None 不限；普通用户传合并后的有效标签，
        三处统计 SQL 共用 `_permission_where` 保证可见性一致。
        """
        document_count = await self.repo.count(permission_tags=permission_tags)
        chunk_count = await self.chunk_repo.count_visible(
            permission_tags=permission_tags
        )
        last_indexed_at = await self.repo.get_last_indexed_at(
            permission_tags=permission_tags
        )
        return KnowledgeBaseStats(
            document_count=document_count,
            chunk_count=chunk_count,
            last_indexed_at=last_indexed_at,
        )

    async def get_chunk(
        self,
        document_id: UUID,
        chunk_id: UUID
    ) -> DocumentChunk:
        # 双重校验：先确保用户能看到 document，再校验 chunk 归属
        await self.get(document_id)
        chunk = await self.chunk_repo.get_for_document(document_id, chunk_id)
        if chunk is None:
            raise NotFoundError("Chunk 不存在")
        return chunk