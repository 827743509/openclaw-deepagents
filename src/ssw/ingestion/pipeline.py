"""文档入库 / 增量索引流水线。

第 12 章重构：
- 由 Celery worker 调度（`app/ingestion/tasks.py`）
- 每次任务全程驱动一条 `ingestion_tasks` 记录的生命周期：pending → running → success/failed
- 增量索引按 `chunk_hash` 对齐：删除失效、保留命中、对新增项重新 embedding
"""

import asyncio
from uuid import UUID

from langchain_core.documents import Document as LangChainDocument

from ssw.config import EMBEDDING_BATCH_SIZE
from ssw.core.logging import get_logger
from ssw.db.models import DocumentStatus, DocumentChunk
from ssw.db.session import AsyncSessionLocal
from ssw.ingestion import embedder, parser, splitter
from ssw.repository.chunk_repo import DocumentChunkRepository
from ssw.repository.document_repo import DocumentRepository
from ssw.storage.file_service import get_file_service

logger = get_logger(__name__)


async def _set_status(
    document_id: UUID,
    status: DocumentStatus,
    *,
    error_message: str | None = None,
) -> None:
    """状态变更独立事务：避免长事务、保证前端轮询能立即看到中间态。"""
    async with AsyncSessionLocal() as session:
        repo = DocumentRepository(session)
        await repo.update_status(document_id, status, error_message=error_message)
        await session.commit()


async def _embed_with_progress(
    texts: list[str], task_id: UUID
) -> list[list[float]]:
    """按 EMBEDDING_BATCH_SIZE 分批 embedding，逐批写入任务进度。

    LangChain `OpenAIEmbeddings.aembed_documents` 内部也会分批，但回调粒度藏在
    SDK 里；这里手动分批是为了让 `progress_done` 跟着每个批次走，前端轮询有连续反馈。
    """


    if not texts:
        return []
    embeddings_client = embedder.get_embeddings()
    batch_size = max(1, EMBEDDING_BATCH_SIZE)
    results: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        vectors = await embeddings_client.aembed_documents(batch)
        results.extend(vectors)

    return results


async def _run_ingest(document_id: UUID, task_id: UUID) -> None:
    """首次入库：全量解析 → 切分 → embedding → 写库。"""
    logger.info("ingest start: document_id=%s task_id=%s", document_id, task_id)


    try:
        async with AsyncSessionLocal() as session:
            document = await DocumentRepository(session).get_by_id(document_id)
            if document is None:
                logger.warning("document not found, skip ingest: %s", document_id)
                return
            object_key = document.oss_object_key
            filename = document.name

        await _set_status(document_id, DocumentStatus.PARSING)
        content = await get_file_service().download(object_key)
        parsed = await parser.parse(filename, content)

        await _set_status(document_id, DocumentStatus.INDEXING)
        chunks = splitter.split(parsed)
        if not chunks:
            raise ValueError("切分后没有任何 chunk，请检查文档内容")


        embeddings = await _embed_with_progress(
            [c.page_content for c in chunks], task_id
        )

        async with AsyncSessionLocal() as session:
            chunk_repo = DocumentChunkRepository(session)
            await chunk_repo.bulk_add(
                [_make_chunk(document_id, c, vec) for c, vec in zip(chunks, embeddings, strict=True)]
            )
            await session.commit()

        await _set_status(document_id, DocumentStatus.READY, error_message=None)

        logger.info("ingest done: document_id=%s chunks=%d", document_id, len(chunks))

    except Exception as exc:
        logger.exception("ingest failed: document_id=%s", document_id)
        message = str(exc).strip() or exc.__class__.__name__
        await _set_status(document_id, DocumentStatus.FAILED, error_message=message[:500])



async def _run_reindex(document_id: UUID, task_id: UUID) -> None:
    """增量重建：按 chunk_hash 对齐，仅对变化部分重新 embedding。

    与 _run_ingest 的区别：
    - 命中的 chunk 不重新计算 embedding，仅更新 chunk_index / metadata
    - 新增 chunk 才走 embedding，progress_total 也只统计新增数量
    - 全删全插作为 hash 冲突场景的兜底
    """
    logger.info("reindex start: document_id=%s task_id=%s", document_id, task_id)


    try:
        async with AsyncSessionLocal() as session:
            document = await DocumentRepository(session).get_by_id(document_id)
            if document is None:
                logger.warning("document not found, skip reindex: %s", document_id)

                return
            object_key = document.oss_object_key
            filename = document.name

        await _set_status(document_id, DocumentStatus.PARSING)
        content = await get_file_service().download(object_key)
        parsed = await parser.parse(filename, content)

        await _set_status(document_id, DocumentStatus.INDEXING)
        new_chunks = splitter.split(parsed)
        if not new_chunks:
            raise ValueError("切分后没有任何 chunk，请检查文档内容")

        # 拉旧 chunks 做 hash 对齐
        async with AsyncSessionLocal() as session:
            old_chunks = await DocumentChunkRepository(session).list_all_by_document(
                document_id
            )

        if _has_duplicate_hash(new_chunks):
            # 同文档内 chunk_hash 重复（多见于极短文档或重复段落），
            # 增量对齐逻辑会歧义；退化为"全删全插"是最稳的兜底
            logger.warning(
                "reindex fallback to full rebuild due to duplicate chunk_hash: %s",
                document_id,
            )
            await _run_full_rebuild(
                document_id, task_id, new_chunks
            )
        else:
            await _run_incremental(
                document_id, task_id, old_chunks, new_chunks
            )

        # 内容已成功重建：版本号 +1
        async with AsyncSessionLocal() as session:
            doc_repo = DocumentRepository(session)
            doc = await doc_repo.get_by_id(document_id)
            if doc is not None:
                doc.version += 1
            await session.commit()

        await _set_status(document_id, DocumentStatus.READY, error_message=None)

        logger.info(
            "reindex done: document_id=%s new_chunks=%d",
            document_id,
            len(new_chunks),
        )

    except Exception as exc:
        logger.exception("reindex failed: document_id=%s", document_id)
        message = str(exc).strip() or exc.__class__.__name__
        await _set_status(document_id, DocumentStatus.FAILED, error_message=message[:500])



async def _run_incremental(
    document_id: UUID,
    task_id: UUID,
    old_chunks: list[DocumentChunk],
    new_chunks: list[LangChainDocument],
) -> None:
    """按 chunk_hash 对齐增删改。

    分类规则：
    - old 中存在但 new 已经没有的 hash → DELETE
    - new 中已存在的 hash → 只更新 chunk_index / metadata，不重新 embedding
    - new 中不存在于 old 的 hash → INSERT，需要 embedding
    """
    old_by_hash = {c.chunk_hash: c for c in old_chunks}
    new_hashes = {c.metadata["chunk_hash"] for c in new_chunks}

    to_delete_ids: list[UUID] = [
        c.id for c in old_chunks if c.chunk_hash not in new_hashes
    ]
    to_insert: list[LangChainDocument] = []
    to_update: list[tuple[DocumentChunk, LangChainDocument]] = []
    for nc in new_chunks:
        h = nc.metadata["chunk_hash"]
        existing = old_by_hash.get(h)
        if existing is None:
            to_insert.append(nc)
        else:
            to_update.append((existing, nc))


    new_embeddings = await _embed_with_progress(
        [c.page_content for c in to_insert], task_id
    )

    async with AsyncSessionLocal() as session:
        chunk_repo = DocumentChunkRepository(session)
        await chunk_repo.delete_by_ids(to_delete_ids)

        # 更新命中 chunk 的位置 / 段落元数据：内容（即 hash）未变所以不动 embedding
        for old, nc in to_update:
            old.chunk_index = nc.metadata["chunk_index"]
            old.page_no = nc.metadata.get("page_no")
            old.section_path = nc.metadata.get("section_path")
            old.extra_metadata = nc.metadata

        await chunk_repo.bulk_add(
            [
                _make_chunk(document_id, c, vec)
                for c, vec in zip(to_insert, new_embeddings, strict=True)
            ]
        )
        await session.commit()

    logger.info(
        "incremental reindex: doc=%s delete=%d update=%d insert=%d",
        document_id,
        len(to_delete_ids),
        len(to_update),
        len(to_insert),
    )


async def _run_full_rebuild(
    document_id: UUID,
    task_id: UUID,
    new_chunks: list[LangChainDocument],
) -> None:
    """hash 冲突场景的兜底：清空旧 chunks，全量 embedding 后写入。"""

    embeddings = await _embed_with_progress(
        [c.page_content for c in new_chunks], task_id
    )

    async with AsyncSessionLocal() as session:
        chunk_repo = DocumentChunkRepository(session)
        await chunk_repo.delete_by_document(document_id)
        await chunk_repo.bulk_add(
            [
                _make_chunk(document_id, c, vec)
                for c, vec in zip(new_chunks, embeddings, strict=True)
            ]
        )
        await session.commit()


def _has_duplicate_hash(chunks: list[LangChainDocument]) -> bool:
    seen: set[str] = set()
    for c in chunks:
        h = c.metadata["chunk_hash"]
        if h in seen:
            return True
        seen.add(h)
    return False


def _make_chunk(
    document_id: UUID, chunk: LangChainDocument, embedding: list[float]
) -> DocumentChunk:
    return DocumentChunk(
        document_id=document_id,
        content=chunk.page_content,
        embedding=embedding,
        page_no=chunk.metadata.get("page_no"),
        section_path=chunk.metadata.get("section_path"),
        chunk_index=chunk.metadata["chunk_index"],
        chunk_hash=chunk.metadata["chunk_hash"],
        extra_metadata=chunk.metadata,
    )


# ---------- 同步入口：供 Celery worker 调用 ----------


def run_ingest_sync(document_id: UUID, task_id: UUID) -> None:
    asyncio.run(_run_ingest(document_id, task_id))


def run_reindex_sync(document_id: UUID, task_id: UUID) -> None:
    asyncio.run(_run_reindex(document_id, task_id))
