"""document_chunks 表访问层。"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from ssw.db.models import DocumentChunk, Document

# 通配权限标签：admin 角色持有，含义"无视权限过滤"
WILDCARD_PERMISSION_TAG = "*"





@dataclass(frozen=True)
class ChunkStats:
    """单个文档下的 chunk 长度统计。

    全部 None 表示该文档当前没有任何 chunk（未入库 / 入库失败）。
    """

    total: int
    avg_length: int
    min_length: int
    max_length: int


class DocumentChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def bulk_add(self, chunks: Sequence[DocumentChunk]) -> None:
        if not chunks:
            return
        self.session.add_all(chunks)
        await self.session.flush()

    async def delete_by_document(self, document_id: UUID) -> None:
        stmt = delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        await self.session.execute(stmt)

    async def delete_by_ids(self, chunk_ids: Sequence[UUID]) -> None:
        """按 id 批量删除：增量索引"删除失效 chunks"用。"""
        if not chunk_ids:
            return
        stmt = delete(DocumentChunk).where(DocumentChunk.id.in_(list(chunk_ids)))
        await self.session.execute(stmt)

    async def list_all_by_document(
        self, document_id: UUID
    ) -> list[DocumentChunk]:
        """拉取一篇文档的全部 chunks。

        增量索引比对旧 chunk_hash 用；文档 chunks 数量上限受 splitter 控制
        （单文档 50MB → 数百条 chunk 量级），一次性加载内存可承受。
        """
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_paginated_by_document(
        self,
        document_id: UUID,
        page: int,
        page_size: int,
    ) -> tuple[list[DocumentChunk], int]:
        offset = (page - 1) * page_size
        items_stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
            .offset(offset)
            .limit(page_size)
        )
        count_stmt = (
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
        )
        items = (await self.session.execute(items_stmt)).scalars().all()
        total = (await self.session.execute(count_stmt)).scalar_one()
        return list(items), int(total)

    async def get_for_document(
        self, document_id: UUID, chunk_id: UUID
    ) -> DocumentChunk | None:
        """按 document_id + chunk_id 双条件查询。

        强校验归属，避免拿 A 文档的 id 越权读 B 文档的 chunk。
        """
        stmt = select(DocumentChunk).where(
            DocumentChunk.id == chunk_id,
            DocumentChunk.document_id == document_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def keyword_search(
        self,
        query: str,
        top_k: int,
        *,
        permission_tags: list[str] | None = None,
    ) -> list[tuple[DocumentChunk, float]]:
        """中文全文检索 Top-K：plainto_tsquery + ts_rank。

        - 用 chinese_zh 文本搜索配置（zhparser 切词，迁移里建好）
        - plainto_tsquery：自动把多个词 AND 起来，对用户输入容错最好
          （"差旅 报销"和"差旅报销"都会切成同一组 token）
        - 仅命中 status='ready' 文档，避免拿到尚未完成入库的脏 chunk
        - permission_tags：用户有效权限标签；None / 含 "*" 不限；其他按数组重叠 + 空标签公开
        """
        tsquery = func.plainto_tsquery("chinese_zh", query)
        rank_expr = func.ts_rank(DocumentChunk.content_tsv, tsquery)
        conditions: list[ColumnElement[bool]] = [
            Document.status == "ready",
            DocumentChunk.content_tsv.op("@@")(tsquery),
        ]
        # perm_where = _permission_where(permission_tags)
        # if perm_where is not None:
        #     conditions.append(perm_where)

        stmt = (
            select(DocumentChunk, rank_expr.label("rank"))
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(and_(*conditions))
            .order_by(rank_expr.desc())
            .limit(top_k)
            .options(selectinload(DocumentChunk.document))
        )
        rows = (await self.session.execute(stmt)).all()
        return [(chunk, float(rank)) for chunk, rank in rows]

    async def vector_search(
        self,
        query_embedding: list[float],
        top_k: int,
        *,
        permission_tags: list[str] | None = None,
    ) -> list[tuple[DocumentChunk, float]]:
        """按 cosine 距离做 Top-K 向量检索。

        - 仅检索状态为 ready 的文档（避免拿到尚未完成入库的脏 chunk）
        - permission_tags：用户有效权限标签；None / 含 "*" 不限；其他按数组重叠 + 空标签公开
        - 返回 (chunk, distance) 列表，distance 越小越相似（pgvector cosine_distance）
        - 用 selectinload 把所属 Document 一并加载，方便上层直接读 document.name
          而不会再发 N 次 lazy load 查询
        """
        distance = DocumentChunk.embedding.cosine_distance(query_embedding)
        conditions: list[ColumnElement[bool]] = [Document.status == "ready"]
        # perm_where = _permission_where(permission_tags)
        # if perm_where is not None:
        #     conditions.append(perm_where)

        stmt = (
            select(DocumentChunk, distance.label("distance"))
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(and_(*conditions))
            .order_by(distance.asc())
            .limit(top_k)
            .options(selectinload(DocumentChunk.document))
        )
        rows = (await self.session.execute(stmt)).all()
        return [(chunk, float(dist)) for chunk, dist in rows]

    async def count_visible(
        self,
        *,
        permission_tags: list[str] | None = None,
    ) -> int:
        """统计可见 chunks 总数。仅命中 status='ready' 文档，与检索口径一致。

        MCP get_knowledge_base_stats 用：让外部 Agent 看到的"知识库规模"
        与实际可被检索到的 chunk 数量对齐。
        """
        stmt = (
            select(func.count())
            .select_from(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(Document.status == "ready")
        )
        # perm_where = _permission_where(permission_tags)
        # if perm_where is not None:
        #     stmt = stmt.where(perm_where)
        return int((await self.session.execute(stmt)).scalar_one())

    async def get_stats(self, document_id: UUID) -> ChunkStats | None:
        """一条聚合 SQL 拿到 count/avg/min/max，避免在 Python 侧再扫一遍 chunks。"""
        length = func.char_length(DocumentChunk.content)
        stmt = select(
            func.count().label("total"),
            func.avg(length).label("avg_len"),
            func.min(length).label("min_len"),
            func.max(length).label("max_len"),
        ).where(DocumentChunk.document_id == document_id)
        row = (await self.session.execute(stmt)).one()
        if not row.total:
            return None
        return ChunkStats(
            total=int(row.total),
            avg_length=int(row.avg_len or 0),
            min_length=int(row.min_len or 0),
            max_length=int(row.max_len or 0),
        )
