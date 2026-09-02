from datetime import datetime
from enum import Enum


from sqlalchemy import ForeignKey, Computed
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB, TSVECTOR
from sqlalchemy.sql.functions import func
from sqlalchemy.sql.sqltypes import String, BigInteger, Text, Integer, DateTime
from pgvector.sqlalchemy import Vector
from ssw.config import EMBEDDING_DIM
from ssw.db.base import Base
from uuid import UUID, uuid4

class DocumentStatus(str, Enum):
    """文档生命周期状态。

    uploading: 已写入 COS、入库前
    parsing:   Docling 解析中
    indexing:  切分 + 向量化 + 写 chunks 中
    ready:     可被检索
    failed:    任意阶段失败
    """

    UPLOADING = "uploading"
    PARSING = "parsing"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"

class IngestionTaskType(str, Enum):
    """入库任务类型。

    ingest:  首次入库（解析 → 切分 → 全量 embedding → 写入）
    reindex: 增量重建（按 chunk_hash 对齐，仅对变化 chunk 重新 embedding）
    """

    INGEST = "ingest"
    REINDEX = "reindex"


class IngestionTaskStatus(str, Enum):
    """Celery 任务生命周期。

    pending: 已入库表、还没被 worker 拉走
    running: worker 已开始执行
    success / failed: 终态
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    # sha256 十六进制串长度 64；唯一约束保证文件级幂等
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    oss_bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    oss_object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        String(32), nullable=False, default=DocumentStatus.UPLOADING
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 文档版本号：每次 reindex 成功后 +1，前端列表可见
    # 不存历史版本快照（不引入 document_versions 表），仅作"内容已变更"的可视化标识
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 上传者；用户被硬删后该字段置 NULL，文档历史仍保留
    created_by: Mapped[str | None] = mapped_column(
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )

class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 维度由 settings.embedding_dim 控制，迁移时同步固化
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)

    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # section_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # md5(content)，第 12 章增量索引依据
    chunk_hash: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    extra_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )

    # 中文全文检索索引列。
    # GENERATED ALWAYS 由 PostgreSQL 根据 content 自动维护，应用层不写、只读。
    # SQLAlchemy 看到 Computed(persisted=True) 会自动从 INSERT/UPDATE 中排除该列。
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('chinese_zh', content)", persisted=True),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="chunks")

class IngestionTask(Base):
    """文档入库任务记录。

    Celery 拉起 worker 前先在 DB 落一条 pending 行；worker 内根据生命周期更新
    running → success/failed。前端轮询 documents 接口附带 `latest_task` 即可
    展示进度（progress_total / progress_done）与失败原因。
    """

    __tablename__ = "ingestion_tasks"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_type: Mapped[IngestionTaskType] = mapped_column(String(16), nullable=False)
    status: Mapped[IngestionTaskStatus] = mapped_column(
        String(16), nullable=False, default=IngestionTaskStatus.PENDING
    )
    # Celery 当前 attempt 次数（Celery 内 retry 时 worker 写入），仅作展示用
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 进度：reindex 时 total=新增 chunks 数，done=已 embedding 的批次累计
    # ingest 走全量 embedding，total=切分后总 chunks 数
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="ingestion_tasks")