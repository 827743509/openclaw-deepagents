"""文档管理 API：上传、列表、详情、删除、重试、下载/预览、chunk 浏览、改权限标签、重新索引。

第 11 章接入认证与权限：
- 读接口（list / get / chunks / download）→ CurrentUser，按 permission_tags 过滤
- 写接口（upload / delete / retry / update tags / reindex）→ CurrentAdmin
"""


from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, File, Query, Response, UploadFile
from starlette.requests import Request

from ssw.db.models import Document, DocumentStatus
from ssw.dependency import DocumentServiceDep
from ssw.schemas.documents import DocumentRead, IngestionTaskRead, DocumentStatusValue, DocumentListResponse, \
    DocumentChunkListResponse, DocumentChunkRead, DocumentChunkStats, DocumentChunkDetail
from ssw.service.document_service import DocumentService

documents_router = APIRouter(prefix="/documents", tags=["documents"])

# DOCX 即便 ?download=0 也强制 attachment：浏览器无法内联渲染 DOCX
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"



@documents_router.post("", response_model=DocumentRead, status_code=201, operation_id="uploadDocument")
async def upload_document(
    service: DocumentServiceDep,
    http_request: Request,
    file: UploadFile = File(..., description="待上传文档（PDF / DOCX / Markdown / HTML）")
) -> DocumentRead:
    """上传文档：写入 COS、落库后立即返回，解析与向量化由 Celery worker 异步执行。"""

    document = await service.upload(
        file,
        created_by=http_request.state.user_id
    )
    return await _to_document_read(document, service)


@documents_router.get("", response_model=DocumentListResponse, operation_id="listDocuments")
async def list_documents(
    service: DocumentServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: DocumentStatusValue | None = Query(None, description="按文档状态筛选"),
) -> DocumentListResponse:
    items, total = await service.list_documents(
        page,
        page_size,
        status=DocumentStatus(status) if status else None,
    )
    return DocumentListResponse(
        items=[await _to_document_read(d, service) for d in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@documents_router.get("/{document_id}", response_model=DocumentRead, operation_id="getDocument")
async def get_document(
    document_id: UUID,
    service: DocumentServiceDep,
) -> DocumentRead:
    document = await service.get(document_id)
    return await _to_document_read(document, service)


@documents_router.delete("/{document_id}", status_code=204, operation_id="deleteDocument")
async def delete_document(
    document_id: UUID,
    service: DocumentServiceDep,
) -> Response:

    await service.delete(document_id)
    return Response(status_code=204)


@documents_router.post(
    "/{document_id}/retry",
    response_model=DocumentRead,
    operation_id="retryDocument",
)
async def retry_document(
    document_id: UUID,
    service: DocumentServiceDep,
) -> DocumentRead:
    document = await service.retry(document_id)
    return await _to_document_read(document, service)


@documents_router.post(
    "/{document_id}/reindex",
    response_model=DocumentRead,
    operation_id="reindexDocument",
)
async def reindex_document(
    document_id: UUID,
    service: DocumentServiceDep,
    file: UploadFile = File(
        ..., description="新版本文件（MIME 必须与原文档一致）"
    ),
) -> DocumentRead:
    """上传新版本文件，触发按 chunk_hash 对齐的增量重建。"""
    document = await service.reindex(document_id, file)
    return await _to_document_read(document, service)





@documents_router.get("/{document_id}/file", operation_id="downloadDocument")
async def download_document(
    document_id: UUID,
    service: DocumentServiceDep,
    download: int = Query(0, ge=0, le=1, description="1=强制下载, 0=尝试内联预览"),
) -> Response:
    """返回文档原始字节。

    支持两种认证方式（优先 header）：
    - Authorization header（常规 fetch 请求）
    - ?token= query 参数（iframe / 浏览器直接打开时无法带 header）
    """


    document = await service.get(document_id)
    content = await service.file_service.download(document.cos_object_key)

    force_attachment = download == 1 or document.mime_type == _DOCX_MIME
    disposition = "attachment" if force_attachment else "inline"
    # RFC 5987 编码非 ASCII 文件名，避免中文文件名报错
    filename_quoted = quote(document.name, safe="")

    return Response(
        content=content,
        media_type=document.mime_type,
        headers={
            "Content-Disposition": (
                f"{disposition}; filename*=UTF-8''{filename_quoted}"
            ),
        },
    )


@documents_router.get(
    "/{document_id}/chunks",
    response_model=DocumentChunkListResponse,
    operation_id="listDocumentChunks",
)
async def list_document_chunks(
    document_id: UUID,
    service: DocumentServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> DocumentChunkListResponse:
    items, total, stats = await service.list_chunks(
        document_id, page, page_size
    )
    return DocumentChunkListResponse(
        items=[DocumentChunkRead.from_orm_chunk(c) for c in items],
        total=total,
        page=page,
        page_size=page_size,
        stats=DocumentChunkStats(
            total=stats.total,
            avg_length=stats.avg_length,
            min_length=stats.min_length,
            max_length=stats.max_length,
        )
        if stats is not None
        else None,
    )


@documents_router.get(
    "/{document_id}/chunks/{chunk_id}",
    response_model=DocumentChunkDetail,
    operation_id="getDocumentChunk",
)
async def get_document_chunk(
    document_id: UUID,
    chunk_id: UUID,
    service: DocumentServiceDep
) -> DocumentChunkDetail:
    chunk = await service.get_chunk(
        document_id, chunk_id
    )
    return DocumentChunkDetail.from_orm_chunk(chunk)


async def _to_document_read(
    document: Document, service: DocumentService
) -> DocumentRead:
    """组装 DocumentRead：附带 latest_task，前端轮询时直接展示任务进度卡片。"""
    latest = await service.get_latest_task(document.id)
    return DocumentRead.model_validate(
        {
            **{c.name: getattr(document, c.name) for c in document.__table__.columns},
            "latest_task": IngestionTaskRead.model_validate(latest)
            if latest is not None
            else None,
        }
    )